"""Tính lại phân bố góc thô khung GOOD dùng để chọn ngưỡng calib_* (calibration.py):  python calib_threshold_stats.py

frames_labeled.csv đã TRỪ baseline nên không cho góc thô tuyệt đối. Góc thô tái dựng = góc đã trừ baseline + baseline thô của
đúng phiên. Baseline thô lấy từ output notebook ChayKaggle/notebook067dc83140.ipynb (cell 10) và hai lần chạy thật
(api_handover/sample_data/p01_events.jsonl; lần chạy của chủ dự án 18/10: neck 26,8, trunk 0,9).
"""
import csv, numpy as np
rows=list(csv.DictReader(open("frames_labeled.csv",encoding="utf-8")))
def f(k): return np.array([float(r[k]) if r[k]!="" else np.nan for r in rows])
neck,trunk,lab=f("neck"),f("trunk"),f("label")
vis=np.minimum(np.minimum(f("vis_ear"),f("vis_shoulder")),f("vis_hip"))
clip=np.array([r["clip"] for r in rows]); ps=np.array([r["person"]+"_"+r["session"] for r in rows])
base=np.array([c.rsplit("_",1)[0] if c[-1].isdigit() else c for c in clip])
ok=(vis>=0.5)&np.isfinite(neck)&np.isfinite(trunk)
# baseline thô (neck, trunk) in từ notebook Kaggle (notebook067dc83140.ipynb, cell 10); P01_S01 có 2 setup -> head_vert gần như nhau
B={"P01_S01":[(37.0,-15.6),(25.0,-3.4)],"P01_S02":[(23.0,-7.3)],"P02_S01":[(22.8,-1.5)],"P02_S02":[(17.5,-1.3)],"P03_S01":[(22.8,-1.0)],"P03_S02":[(19.4,-0.4)]}
print("head_vert (neck+trunk) baseline từng phiên:",{k:[round(n+t,1) for n,t in v] for k,v in B.items()})
good=ok&(base=="GOOD")&(lab==0)
def P(x): return "n=%d p50=%.1f p90=%.1f p95=%.1f p99=%.1f max=%.1f"%(len(x),np.percentile(x,50),np.percentile(x,90),np.percentile(x,95),np.percentile(x,99),x.max())
for name,metric in (("ĐẦU so với đứng (neck+trunk)",lambda n,t:n+t),("neck thô (vai→tai − thân)",lambda n,t:n),("trunk thô",lambda n,t:t)):
    allv=[]
    for s,bl in B.items():
        m=good&(ps==s)
        for bn,bt in bl:
            allv.append(metric(neck[m]+bn,trunk[m]+bt)/ (1 if len(bl)==1 else 1))
    x=np.concatenate(allv)
    print(f"GOOD tái dựng (dataset, 6 phiên) {name}: {P(x)}")
# thêm baseline thật chạy trực tiếp: P01 sample (24.59,-5.79) và ngồi thẳng của bạn (26.8,0.91): dùng rel pooled của GOOD
rel_n,rel_t=neck[good],trunk[good]
def extra(bl): return np.concatenate([ (rel_n+bn)+(rel_t+bt) for bn,bt in bl ])
live=[(24.59,-5.79),(26.8,0.91)]
dsv=np.concatenate([ (neck[good&(ps==s)]+bn)+(trunk[good&(ps==s)]+bt) for s,bl in B.items() for bn,bt in bl ])
print("GOOD tái dựng + 2 baseline chạy thật (ngồi thẳng) đầu so với đứng:",P(np.concatenate([dsv,extra(live)])))
print("  baseline đầu so với đứng, 6 phiên dataset + 2 live:", sorted(round(n+t,1) for s,bl in B.items() for n,t in bl[:1])+[round(a+b,1) for a,b in live])
# BAD: đầu so với đứng thô = rel + baseline (đầu ~21): phần tử đầu cúi
for b in ("FORWARD_HEAD","SLOUCH","LEAN_FORWARD"):
    m=ok&(base==b)&(lab==1); x=np.concatenate([(neck[m&(ps==s)]+trunk[m&(ps==s)])+bl[0][0]+bl[0][1] for s,bl in B.items() if (m&(ps==s)).any()])
    print(f"BAD {b} đầu thô tái dựng: {P(x)}  | tỉ lệ <= 30: {np.mean(x<=30)*100:.1f}%  <=35: {np.mean(x<=35)*100:.1f}%")
# trunk: ngả sau
for s,bl in B.items(): pass
m=ok&(base=="LEAN_BACKWARD")&(lab==1)
x=np.concatenate([(trunk[m&(ps==s)])+np.mean([b[1] for b in bl]) for s,bl in B.items() if (m&(ps==s)).any()])
print("LEAN_BACKWARD trunk thô tái dựng:",P(x), "| tỉ lệ < -20:",round(np.mean(x<-20)*100,1),"% < -15:",round(np.mean(x<-15)*100,1),"%")
g=np.concatenate([ (trunk[good&(ps==s)])+bt for s,bl in B.items() for bn,bt in bl])
print("GOOD trunk thô tái dựng: %s | tỉ lệ < -20: %.2f%%  < -15: %.2f%% < -25: %.2f%%"%(P(g),np.mean(g<-20)*100,np.mean(g<-15)*100,np.mean(g<-25)*100))
print("-----")
allx=np.concatenate([dsv,extra(live)])
for q in (0.1,1,5): print("GOOD đầu thô p%s = %.1f"%(q,np.percentile(allx,q)), "| dataset-only %.1f"%np.percentile(dsv,q))
for b in ("SLOUCH","LEAN_FORWARD"):
    m=ok&(base==b)&(lab==1)
    x=np.concatenate([trunk[m&(ps==s)]+np.mean([q[1] for q in bl]) for s,bl in B.items() if (m&(ps==s)).any()])
    print(b,"trunk thô BAD:",P(x),"| <=20: %.1f%% <=10: %.1f%%"%(np.mean(x<=20)*100,np.mean(x<=10)*100))
print("GOOD trunk thô > 10: %.2f%%  > 20: %.2f%%"%(np.mean(g>10)*100,np.mean(g>20)*100))
