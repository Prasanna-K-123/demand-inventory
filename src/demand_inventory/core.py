import math
import numpy as np
from ._contracts import sba_inputs, target_inputs, allocation_inputs, simulation_inputs

QUANTILES=np.array([.1,.5,.8,.9])
FEATURES=['item','department','store','next_month','sin_day','cos_day','sum7','sum14','sum28','sum56',
          'recent_week_ratio','zero28','zero56','age_active','never_active','last_observed_price','price_missing']

def sba_path(sales,alpha=.1):
    y,alpha=sba_inputs(sales,alpha)
    if not 0<alpha<1 or y.ndim!=1 or np.any(y<0):raise ValueError('Invalid SBA data')
    out=np.zeros(len(y));q=period=None;last=None
    for j,x in enumerate(y):
        if x>0:
            if q is None:q=x;period=j+1
            else:q=(1-alpha)*q+alpha*x;period=(1-alpha)*period+alpha*(j-last)
            last=j
        out[j]=(1-alpha/2)*q/period if q is not None else 0.
    return out

def features(sales,prices,dates,meta_codes,origin):
    y,p=np.asarray(sales),np.asarray(prices)
    if origin<56 or origin>y.shape[1] or p.shape!=y.shape:raise ValueError('Invalid origin/panel')
    n=y.shape[0];end=origin
    sums=[y[:,end-k:end].sum(axis=1) for k in [7,14,28,56]]
    previous=y[:,end-14:end-7].sum(axis=1)
    recent=sums[0]/np.maximum(previous,1)
    z=[(y[:,end-k:end]==0).mean(axis=1) for k in [28,56]]
    seen=y[:,:end]>0;active=seen.any(axis=1);first=seen.argmax(axis=1)
    age=np.where(active,end-first,0)
    date=np.datetime64(int(dates[end-1])+1,'D');year=date.astype('datetime64[Y]');doy=int((date-year).astype(int))+1
    month=int(str(date)[5:7]);theta=2*math.pi*doy/365.25
    last=p[:,end-1];missing=~np.isfinite(last)
    return np.column_stack([meta_codes,np.full(n,month),np.full(n,math.sin(theta)),np.full(n,math.cos(theta)),
                            *sums,recent,*z,age,(~active).astype(float),last,missing.astype(float)])

def targets(sales,origin,horizon=14):
    sales,origin,horizon=target_inputs(sales,origin,horizon)
    if origin+horizon>sales.shape[1]:raise ValueError('Target truncated')
    return np.asarray(sales)[:,origin:origin+horizon].sum(axis=1)

def coherent(pred):
    p=np.asarray(pred,float)
    if p.ndim!=2 or p.shape[1]!=4 or not np.isfinite(p).all():raise ValueError('Invalid quantiles')
    return np.maximum(np.sort(p,axis=1),0.)

def pinball(y,pred):
    e=np.asarray(y)[:,None]-np.asarray(pred)
    return np.maximum(QUANTILES*e,(QUANTILES-1)*e)

def metrics(y,p):
    y=np.asarray(y);p=np.asarray(p);err=np.abs(y-p[:,1]);den=y.sum()
    return {'mean_pinball':float(pinball(y,p).mean()),'mae_median':float(err.mean()),
        'wape_median':float(err.sum()/den) if den>0 else None,
        'interval80_coverage':float(((y>=p[:,0])&(y<=p[:,3])).mean()),
        'interval80_width':float((p[:,3]-p[:,0]).mean()),'q80_empirical_fraction_leq':float((y<=p[:,2]).mean()),
        'observations':len(y),'actual_units_14day':float(den)}

def allocate(desired,cost,penalty,coverage,ids,budget,capacity):
    desired,cost,penalty,coverage,ids,budget,capacity=allocation_inputs(desired,cost,penalty,coverage,ids,budget,capacity)
    d=np.asarray(desired,float);c=np.asarray(cost,float)
    if len(d)!=len(c) or np.any(d<0) or budget<0 or capacity<0:raise ValueError('Invalid allocation inputs')
    order=np.zeros(len(d),int);left=float(budget);units=int(math.floor(capacity))
    priority=sorted(range(len(d)),key=lambda j:(-round(float(penalty[j]/c[j]),12) if np.isfinite(c[j]) and c[j]>0 else float('inf'),float(coverage[j]),str(ids[j])))
    for j in priority:
        if not np.isfinite(c[j]) or c[j]<=0:continue
        q=min(int(math.ceil(d[j])),units,max(int(math.floor((left+1e-9)/c[j])),0))
        if q>0:order[j]=q;left-=q*c[j];units-=q
    if np.dot(order,np.nan_to_num(c))>budget+1e-6 or order.sum()>math.floor(capacity):raise RuntimeError('Allocation constraint failure')
    return order

def simulate(sales,price,origins,quantiles,ids,budget_multiplier=1.,lead_weeks=1,shortage_fraction=.4,censor=False):
    sales,price,origins,quantiles,ids,budget_multiplier,lead_weeks,shortage_fraction,censor=simulation_inputs(
        sales,price,origins,quantiles,ids,budget_multiplier,lead_weeks,shortage_fraction,censor)
    n=len(ids);stock=np.zeros(n);pending=[];rows=[];byseries=np.zeros((n,4))
    for step,origin in enumerate(origins):
        opening=stock.copy();arrival=np.zeros(n)
        for due,q in pending:
            if due==step:arrival+=q
        pending=[(due,q) for due,q in pending if due!=step];stock+=arrival
        prices=price[:,origin-1];cost=.6*prices;known=np.isfinite(cost)&(cost>0)
        trailing=sales[:,origin-28:origin].sum(axis=1)/4
        budget=budget_multiplier*float(np.dot(trailing[known],cost[known]));capacity=2*float(trailing.sum())
        inpipe=sum((q for _,q in pending),np.zeros(n))
        target=np.ceil(quantiles[step,:,2]);desired=np.maximum(target-stock-inpipe,0.)
        coverage=stock/np.maximum(trailing,1.)
        orders=allocate(desired,cost,shortage_fraction*prices,coverage,ids,budget,capacity)
        pending.append((step+lead_weeks,orders.copy()))
        observed=targets(sales,origin,7);demand=observed.copy()
        if censor:demand+=np.where(observed==0,.25*trailing,0.)
        filled=np.minimum(stock,demand);lost=demand-filled;stock-=filled
        # Unknown price is not converted to a fabricated cost. Units remain in service metrics.
        hold=float(np.dot(stock[known],.1*prices[known]));short=float(np.dot(lost[known],shortage_fraction*prices[known]));spend=float(np.dot(orders[known],cost[known]))
        if np.max(np.abs(opening+arrival-filled-stock))>1e-8 or stock.min()<-1e-8:raise RuntimeError('Stock flow identity failed')
        row={'origin':int(origin),'budget':budget,'capacity_units':int(math.floor(capacity)),
             'ordered_units':int(orders.sum()),'procurement_spend':spend,'holding_penalty':hold,'lost_sales_penalty':short,
             'total_penalty':hold+short,'demand_proxy_units':float(demand.sum()),'filled_units':float(filled.sum()),
             'lost_units':float(lost.sum()),'ending_inventory_units':float(stock.sum()),
             'pipeline_units':float(sum(q.sum() for _,q in pending)),
             'unknown_price_series':int((~known).sum()),'unknown_price_demand_units':float(demand[~known].sum())}
        rows.append(row);byseries[:,0]+=demand;byseries[:,1]+=filled;byseries[:,2]+=lost;byseries[:,3]+=orders
    full={key:float(sum(x[key] for x in rows)) for key in ['procurement_spend','holding_penalty','lost_sales_penalty','total_penalty','demand_proxy_units','filled_units','lost_units','unknown_price_demand_units']}
    full.update({'unit_fill_rate':full['filled_units']/full['demand_proxy_units'] if full['demand_proxy_units'] else None,
                 'ending_inventory_units':float(stock.sum()),'ending_pipeline_units':float(sum(q.sum() for _,q in pending)),
                 'startup_first_week_penalty':rows[0]['total_penalty'],'weeks':len(rows),
                 'budget_multiplier':budget_multiplier,'lead_weeks':lead_weeks,'shortage_fraction':shortage_fraction,'censor_proxy':censor,
                 'post_startup_penalty':sum(x['total_penalty'] for x in rows[1:]),
                 'rows':rows,'by_series':byseries.tolist()})
    return full
