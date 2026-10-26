"""Full-file type and unused-covariate checks, separate from predictive features."""
import argparse,json
from pathlib import Path
import duckdb
from stockout.common import atomic_json,file_hash
from stockout.contracts import SaleEvent,BatchRequest,JobRequest,JobResult
BASE=Path(__file__).resolve().parents[1]
EXPECTED={"city_id":"BIGINT","store_id":"BIGINT","management_group_id":"BIGINT","first_category_id":"BIGINT","second_category_id":"BIGINT","third_category_id":"BIGINT","product_id":"BIGINT","dt":"VARCHAR","sale_amount":"DOUBLE","hours_sale":"DOUBLE[]","stock_hour6_22_cnt":"INTEGER","hours_stock_status":"INTEGER[]","activity_flag":"INTEGER","discount":"DOUBLE","holiday_flag":"INTEGER","precpt":"DOUBLE","avg_temperature":"DOUBLE","avg_humidity":"DOUBLE","avg_wind_level":"DOUBLE"}
def run(data):
    con=duckdb.connect();con.execute("set threads=2")
    audit=json.loads((BASE/"artifacts/source_audit.json").read_text());protocol=json.loads((BASE/"protocol.json").read_text())
    for split in ["train","eval"]:
        path=data/f"fresh-lt-{split}.parquet";assert file_hash(path)==protocol["source"][split+"_sha256"]
        con.execute("create or replace temp view raw_source as select * from read_parquet('"+str(path.resolve()).replace("\\","/").replace("'","''")+"')")
        actual={r[0]:r[1] for r in con.execute("describe raw_source").fetchall()};assert actual==EXPECTED
        checks=[]
        for col in ["city_id","store_id","management_group_id","first_category_id","second_category_id","third_category_id","product_id"]:checks.append(f"{col} is null or {col}<0")
        for col in ["discount","precpt","avg_temperature","avg_humidity","avg_wind_level"]:checks.append(f"{col} is null or not isfinite({col})")
        for col in ["activity_flag","holiday_flag"]:checks.append(f"{col} is null or {col} not in (0,1)")
        invalid=con.execute("select sum(case when "+" or ".join(checks)+" then 1 else 0 end) from raw_source").fetchall()[0][0]
        dates=con.execute("select sum(case when strftime(try_cast(dt as date),'%Y-%m-%d') != dt then 1 else 0 end) from raw_source").fetchall()[0][0]
        audit[split]["all_19_columns_exact_type_match"]=True;audit[split]["metadata_or_unused_covariate_invalid_rows"]=invalid;audit[split]["noncanonical_date_rows"]=dates
        assert invalid==0 and dates==0
    atomic_json(BASE/"artifacts/source_audit.json",audit)
    atomic_json(BASE/"docs/source_schema.json",{"dataset":"FreshRetailNet-LT","fields":EXPECTED,"prediction_policy":"Only historical daily sales and historical business-hour stockout counts plus calendar are used; unused source fields audited but excluded from predictors."})
    atomic_json(BASE/"docs/event.schema.json",SaleEvent.model_json_schema());atomic_json(BASE/"docs/batch.schema.json",BatchRequest.model_json_schema());atomic_json(BASE/"docs/job.schema.json",JobRequest.model_json_schema());atomic_json(BASE/"docs/result.schema.json",JobResult.model_json_schema())
    print(json.dumps({split:{k:audit[split][k] for k in ["all_19_columns_exact_type_match","metadata_or_unused_covariate_invalid_rows","noncanonical_date_rows"]} for split in audit}))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--data",type=Path,required=True);run(p.parse_args().data)
