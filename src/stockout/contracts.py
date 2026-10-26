from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from typing import Annotated,Literal
from pydantic import BaseModel,Field,ConfigDict,FiniteFloat,StrictInt,model_validator,field_validator

SHA=Annotated[str,Field(pattern=r"^[0-9a-f]{64}$")]
ID=Annotated[StrictInt,Field(ge=0,le=2**31-1)]
Quantity=Annotated[FiniteFloat,Field(ge=0,le=1_000_000)]
class Contract(BaseModel):
    model_config=ConfigDict(extra="forbid")
class SaleEvent(Contract):
    source_sha256:SHA
    store_id:ID
    product_id:ID
    event_date:date
    arrived_at:datetime
    sale_amount:Quantity
    hours_sale:Annotated[list[Quantity],Field(min_length=24,max_length=24)]
    hours_stock_status:Annotated[list[Literal[0,1]],Field(min_length=24,max_length=24)]
    oos_hours:Annotated[StrictInt,Field(ge=0,le=16)]
    arrival_kind:Literal["synthetic_next_midnight","synthetic_delayed","synthetic_fault_fixture"]
    @model_validator(mode="after")
    def validate_event(self):
        if self.arrived_at.tzinfo is None or self.arrived_at.utcoffset() is None:raise ValueError("arrived_at requires timezone")
        self.arrived_at=self.arrived_at.astimezone(timezone.utc)
        earliest=datetime.combine(self.event_date+timedelta(days=1),datetime.min.time(),timezone.utc)
        if self.arrived_at<earliest:raise ValueError("daily outcome cannot arrive before its day is complete")
        if abs(sum(self.hours_sale)-self.sale_amount)>1e-6:raise ValueError("daily/hourly conservation failure")
        if sum(self.hours_stock_status[6:22])!=self.oos_hours:raise ValueError("business-hour stockout count mismatch")
        return self
    @property
    def key(self):return f"{self.store_id}:{self.product_id}:{self.event_date.isoformat()}"

class BatchRequest(Contract):
    batch_id:Annotated[str,Field(min_length=1,max_length=80,pattern=r"^[A-Za-z0-9_.:-]+$")]
    source_sha256:SHA
    start_offset:Annotated[StrictInt,Field(ge=0)]
    events:Annotated[list[dict],Field(min_length=1,max_length=1000)]

class SeriesKey(Contract):
    store_id:ID
    product_id:ID

class JobRequest(Contract):
    series:Annotated[list[SeriesKey],Field(min_length=1,max_length=64)]
    target_date:date
    as_of:datetime
    model_version:Annotated[str,Field(pattern=r"^[0-9a-f]{16}$")]
    capacity_steps:Annotated[StrictInt,Field(ge=0,le=1000)]|None=None
    shortage_weight:Literal[1,3,5]=3
    @model_validator(mode="after")
    def validate_job(self):
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:raise ValueError("as_of requires timezone")
        self.as_of=self.as_of.astimezone(timezone.utc)
        if self.as_of.date()!=self.target_date:raise ValueError("as_of must be on target_date; one-day forecasting only")
        keys=[(x.store_id,x.product_id) for x in self.series]
        if len(set(keys))!=len(keys):raise ValueError("series identities must be unique")
        return self

class JobStatus(Contract):
    job_id:str
    state:Literal["queued","running","succeeded","failed"]
    attempt:int
    model_version:str
    feature_version:str
    snapshot_seq:int
    error:str|None=None

class JobSubmission(Contract):
    job_id:str
    state:str
    deduplicated:bool

class Prediction(Contract):
    store_id:int
    product_id:int
    target_date:str
    point:float|None
    lower:float|None
    upper:float|None
    policy:str
    decision_allowed:bool
    feature_hash:str
    history_hash:str
    history_rows:int
    last_age_days:int
    interval_model:str

class AllocationResult(Contract):
    quantity_steps:list[int]
    quantities:list[float]
    used_steps:int
    capacity_steps:int
    objective:float
    step:float
    caps:list[int]
    optimality_scope:str
    policy_id:Literal["raw-quantile-point-grid-v1"]
    scenario_definition:str
    scenario_values:list[list[float]]
    shortage_weight:Literal[1,3,5]
    excess_weight:Literal[1.0]

class JobResult(Contract):
    job_id:str
    run_id:str
    model_version:str
    feature_version:str
    snapshot_seq:int
    source_sha256s:list[str]
    as_of:str
    predictions:list[Prediction]
    allocation:AllocationResult|None
    allocation_policy:str
    monitoring:dict
    result_hash:str|None=None
