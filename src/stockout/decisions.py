"""Exact dynamic programming on a finite one-period normalized-capacity grid."""
from __future__ import annotations
import itertools
import numpy as np

def loss(quantity, demand, shortage=3.0, excess=1.0):
    d=np.asarray(demand,float)
    return float(np.mean(shortage*np.maximum(d-quantity,0)+excess*np.maximum(quantity-d,0)))

def allocate(scenarios, capacity_steps, shortage=3.0, excess=1.0, step=0.1, caps=None):
    s=np.asarray(scenarios,float)
    if s.ndim!=2 or not 1<=len(s)<=64 or s.shape[1]<1 or not np.all(np.isfinite(s)) or np.any(s<0):
        raise ValueError("finite nonnegative item-by-scenario matrix required")
    if isinstance(capacity_steps,bool) or int(capacity_steps)!=capacity_steps or not 0<=capacity_steps<=10000:
        raise ValueError("capacity_steps must be an integer in 0..10000")
    if not np.isfinite([step,shortage,excess]).all() or step<=0 or shortage<=0 or excess<=0:
        raise ValueError("positive finite step and cost weights required")
    caps=np.minimum(100,np.ceil(1.5*np.maximum(s.max(axis=1),0.1)/step).astype(int)) if caps is None else np.asarray(caps,int)
    if caps.shape!=(len(s),) or np.any(caps<0) or np.any(caps>10000):raise ValueError("invalid caps")
    b=min(int(capacity_steps),int(caps.sum()))
    prev=np.full(b+1,np.inf);prev[0]=0
    choices=[]
    for i in range(len(s)):
        cur=np.full(b+1,np.inf);choice=np.full(b+1,-1,dtype=int)
        for q in range(min(int(caps[i]),b)+1):
            candidate=prev[:b+1-q]+loss(q*step,s[i],shortage,excess)
            better=candidate<cur[q:]-1e-12
            cur[q:][better]=candidate[better];choice[q:][better]=q
        prev=cur;choices.append(choice)
    remaining=int(np.argmin(prev));objective=float(prev[remaining]);used=remaining;quantities=[]
    for choice in reversed(choices):
        q=int(choice[remaining]);quantities.append(q);remaining-=q
    quantities=np.array(quantities[::-1],int)
    assert remaining==0 and quantities.sum()<=capacity_steps and np.all(quantities<=caps)
    certified=sum(loss(q*step,s[i],shortage,excess) for i,q in enumerate(quantities))
    assert np.isclose(certified,objective)
    return {"quantity_steps":quantities.tolist(),"quantities":(quantities*step).tolist(),
            "used_steps":int(used),"capacity_steps":int(capacity_steps),"objective":objective,
            "step":step,"caps":caps.tolist(),"optimality_scope":"exact finite grid only"}

def brute_force_oracle(scenarios, capacity_steps, caps, shortage=3.0, excess=1.0, step=0.1):
    best=(float("inf"),None)
    for qs in itertools.product(*[range(c+1) for c in caps]):
        if sum(qs)>capacity_steps:continue
        val=sum(loss(q*step,scenarios[i],shortage,excess) for i,q in enumerate(qs))
        if val<best[0]:best=(val,qs)
    return best
