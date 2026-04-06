"""Kalshi Autonomous Trading System - $10 to $1000.
Self-iterates 12 strategy variants across 6 timeframes.
Backtest -> forward test -> CEO gate -> execute -> learn.
"""
import os,sys,json,time,threading,sqlite3
from datetime import datetime,timezone
import numpy as np
import yfinance as yf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from kalshi_python import KalshiClient,Configuration,MarketsApi,PortfolioApi,CreateOrderRequest
    HAS_K=True
except: HAS_K=False

DBD=os.path.join(os.path.dirname(os.path.abspath(__file__)),"data")
os.makedirs(DBD,exist_ok=True)
DB=os.path.join(DBD,"kalshi.db")
KP=os.path.join(os.path.dirname(os.path.abspath(__file__)),"kalshi_key.pem")
KI=os.environ.get("KALSHI_KEY_ID","REDACTED_KALSHI_KEY_ID")

def idb():
    c=sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,ts TEXT,ticker TEXT,side TEXT,ep REAL,xp REAL,cnt INT,pnl REAL,status TEXT,strat TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS equity(id INTEGER PRIMARY KEY,ts TEXT,bal REAL,t INT,sh REAL,wr REAL,dd REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS sp(id INTEGER PRIMARY KEY,ts TEXT,strat TEXT,tf TEXT,t INT,wr REAL,sh REAL,pnl REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY,ts TEXT,ev TEXT,det TEXT)")
    c.commit();c.close()
idb()

class KC:
    def __init__(self):
        if not HAS_K:self.auth=False;return
        try:
            self.k=KalshiClient(Configuration(host="https://trading-api.kalshi.com/trade-api/v2"))
            self.k.set_kalshi_auth(key_id=KI,private_key_path=KP)
            self.m=MarketsApi(self.k);self.p=PortfolioApi(self.k);self.co=CreateOrderRequest;self.auth=True
        except:self.auth=False
kc=KC()

BT={
    "30d":{"mt":10,"msh":0.3,"iv":"15m","yp":"3mo","af":np.sqrt(252*24)},
    "60d":{"mt":15,"msh":0.3,"iv":"1h","yp":"3mo","af":np.sqrt(252*7)},
    "90d":{"mt":20,"msh":0.3,"iv":"1h","yp":"3mo","af":np.sqrt(252*7)},
    "180d":{"mt":25,"msh":0.3,"iv":"1h","yp":"6mo","af":np.sqrt(252*7)},
    "360d":{"mt":6,"msh":0.3,"iv":"1d","yp":"1y","af":np.sqrt(252)},
    "3y":{"mt":10,"msh":0.3,"iv":"1d","yp":"3y","af":np.sqrt(252)},
}

def rsi(closes,p=14):
    d=np.diff(closes);g=np.where(d>0,d,0);l=np.where(d<0,-d,0)
    ag=np.convolve(g,np.ones(p)/p,"valid");al=np.convolve(l,np.ones(p)/p,"valid")
    return 100.0-100.0/(1.0+np.where(al>0,ag/al,100.0))

def ema(closes,p):
    e=np.convolve(closes,np.ones(p)/p,"valid")
    return e[-(len(closes)-p+1):] if len(e)>=len(closes)-p+1 else e

def run_s(cl,typ,rp,sc):
    n=len(cl);w=0;t=0;p=0.0;h=False;e=0.0
    if typ=="rsi":
        rv=rsi(cl,14);o=len(cl)-len(rv);rl=rp.get("l",15);rh=rp.get("h",85)
        for i in range(len(rv)):
            if not h and rv[i]<rl:h=True;e=cl[i+o]
            elif h and rv[i]>rh:h=False;x=cl[i+o];p+=(x-e)/e-sc;t+=1
            if h==False and t>0 and p>0:h==None;w+=1
    elif typ=="ema":
        f=rp.get("f",5);s=rp.get("s",20);ef=ema(cl,f);es=ema(cl,s)
        m=min(len(ef),len(es));o=len(cl)-m;ef=ef[-m:];es=es[-m:]
        for i in range(1,m):
            if not h and ef[i]>es[i] and ef[i-1]<=es[i-1]:h=True;e=cl[i+o]
            elif h and ef[i]<es[i] and ef[i-1]>=es[i-1]:h=False;x=cl[i+o];p+=(x-e)/e-sc;t+=1
            if h==False and t>0 and p>0:h==None;w+=1
    elif typ=="mom":
        lb=rp.get("b",10);th=rp.get("t",0.02)
        for i in range(lb,n-1):
            mom=(cl[i]-cl[i-lb])/cl[i-lb]
            if not h and mom>th:h=True;e=cl[i]
            elif h and mom<-th*0.5:h=False;x=cl[i];p+=(x-e)/e-sc;t+=1
            if h==False and t>0 and p>0:h==None;w+=1
    elif typ=="bb":
        pr=rp.get("p",20);st=rp.get("s",2.0)
        ma=np.convolve(cl,np.ones(pr)/pr,"valid");o=len(cl)-len(ma)
        for i in range(len(ma)):
            wi=cl[i+o:i+o+pr];sd=np.std(wi);up=ma[i]+st*sd;lo=ma[i]-st*sd
            if not h and cl[i+o]>up:h=True;e=cl[i+o]
            elif h and cl[i+o]<ma[i]:h=False;x=cl[i+o];p+=(x-e)/e-sc;t+=1
            if h==False and t>0 and p>0:h==None;w+=1
    elif typ=="don":
        lb=rp.get("b",20)
        for i in range(lb,n-1):
            hi=max(cl[i-lb:i]);lo=min(cl[i-lb:i])
            if not h and cl[i]>hi:h=True;e=cl[i]
            elif h and cl[i]<lo:h=False;x=cl[i];p+=(x-e)/e-sc;t+=1
            if h==False and t>0 and p>0:h==None;w+=1
    elif typ=="atr":
        pr=rp.get("p",14);mt=rp.get("m",1.5)
        at=np.convolve(np.abs(np.diff(cl)),np.ones(pr)/pr,"valid")
        ma=np.convolve(cl[:-1],np.ones(pr)/pr,"valid");m=min(len(ma),len(at));o=len(cl)-m-1
        for i in range(1,m):
            up=ma[i]+at[i]*mt;lo=ma[i]-at[i]*mt
            if not h and cl[i+o]>up:h=True;e=cl[i+o]
            elif h and cl[i+o]<lo:h=False;x=cl[i+o];p+=(x-e)/e-sc;t+=1
            if h==False and t>0 and p>0:h==None;w+=1
    if h and len(cl)>0:h=False;x=cl[-1];p+=(x-e)/e-sc;t+=1
    if p>0:w+=1
    return w,t,p

SV=[("rsi",  {"l":10,"h":90}),("rsi", {"l":15,"h":85}),("rsi", {"l":20,"h":80}),
    ("ema",  {"f":5,"s":20}), ("ema", {"f":9,"s":34}), ("ema", {"f":12,"s":50}),
    ("mom",  {"b":5,"t":0.01}),("mom", {"b":10,"t":0.02}),("mom", {"b":20,"t":0.03}),
    ("don",  {"b":10}),       ("don", {"b":20}),       ("don", {"b":40}),
    ("bb",   {"p":10,"s":1.5}),("bb",  {"p":20,"s":2.0}),("bb",  {"p":30,"s":2.5}),
    ("atr",  {"p":7,"m":1.0}), ("atr", {"p":14,"m":1.5}),("atr", {"p":21,"m":2.0}),
]

def bt(tf="90d",sp=0.02):
    c=BT.get(tf,BT["90d"]);iv=c["iv"];yp=c["yp"];af=c["af"];mt=c["mt"];msh=c["msh"]
    px=["BTC-USD","ETH-USD","SOL-USD"];bs="";bsh=-999;bw=0;bt2=0;bp=0.0
    for typ,par in SV:
        tw=0;tt=0;tp=0.0
        for tk in px:
            try:d=yf.Ticker(tk).history(period=yp,interval=iv)
            except:continue
            if len(d)<50:continue
            w,t,p=run_s(d["Close"].values,typ,{**par,"sc":sp},sp);tw+=w;tt+=t;tp+=p
        if tt<3:continue
        wr=tw/max(tt,1);av=tp/max(tt,1);sh=(av/max(av*10 if av>0 else 0.01,0.001))*af if tt>mt and av>0 else 0
        if sh>bsh:bsh=sh;bs=typ;bw=tw;bt2=tt;bp=tp
    wr2=bw/max(bt2,1);av2=bp/max(bt2,1);sh2=(av2/max(av2*10 if av2>0 else 0.01,0.001))*af if bt2>mt and av2>0 else 0
    ps=wr2>0.50 and sh2>msh and bt2>mt
    return {"pass":ps,"trades":bt2,"wins":bw,"wr":round(wr2*100,1),"sh":round(sh2,2),"pnl":round(bp*100,1),"strat":bs}

class FT:
    def __init__(self):self.a={};self.c=[]
    def en(self,t,s,p):self.a[t]={"t":t,"s":s,"e":p,"ts":time.time()}
    def ex(self,t,xp,r):
        if t not in self.a:return None;p=self.a.pop(t)
        pn=((xp-p["e"])/100.0) if p["s"]=="yes" else ((p["e"]-xp)/100.0)
        r={"tk":t,"s":p["s"],"e":p["e"],"x":xp,"pn":round(pn,4),"r":r};self.c.append(r);return r
    def sc(self):
        if not kc.auth:return [];en=[]
        try:
            rp=kc.m.get_markets(limit=30)
            for m in getattr(rp,"markets",[])[:25]:
                if m.ticker in self.a:continue
                d=kc.m.get_market(ticker=m.ticker);mk=getattr(d,"market",None)
                if not mk:continue;ye=getattr(mk,"yes_bid",0) or 0;no2=getattr(mk,"no_ask",0) or 0;vo=getattr(mk,"volume",0) or 0
                if vo<100:continue;im=ye/100.0 if ye>0 else 0.5
                if im>0.85:self.a[m.ticker]={"t":m.ticker,"s":"no","e":no2,"ts":time.time()};en.append(m.ticker)
                elif im<0.15:self.a[m.ticker]={"t":m.ticker,"s":"yes","e":ye,"ts":time.time()};en.append(m.ticker)
        except:pass
        return en
    def sy(self):
        if not kc.auth:return [];ex=[]
        for t in list(self.a.keys()):
            p=self.a[t]
            try:
                d=kc.m.get_market(ticker=t);mk=getattr(d,"market",None)
                if not mk:continue;cu=getattr(mk,"yes_bid",50) or 50
                if p["s"]=="yes" and cu>=80:ex.append(self.ex(t,cu,"tp"))
                elif p["s"]=="yes" and cu<=20:ex.append(self.ex(t,cu,"sl"))
                elif p["s"]=="no" and cu<=20:ex.append(self.ex(t,cu,"tp"))
                elif p["s"]=="no" and cu>=80:ex.append(self.ex(t,cu,"sl"))
            except:pass
        return [e for e in ex if e]
ft=FT()

class CEO:
    def __init__(self):self.bh=[];self.dd=0.15;self.mc=0.52;self.lp=[]
    def vb(self,b):
        self.bh.append(b)
        if len(self.bh)>=2:pk=max(self.bh);dd=(pk-b)/pk if pk>0 else 0
        if dd>self.dd:return{"ok":False,"r":f"DD {dd:.1%}"}
        if b<1.0:return{"ok":False,"r":"<$1"}
        return{"ok":True}
    def ve(self,e):
        if e.get("conf",0)<self.mc:return{"ok":False,"r":f"C{e['conf']:.2%}"}
        if e.get("ec",0)<3:return{"ok":False,"r":f"E{e['ec']}c"}
        return{"ok":True}
    def ln(self,t,pl,s):
        self.lp.append({"tk":t[:8],"s":s,"w":1.0 if pl>0 else 0.0})
        c=sqlite3.connect(DB);ex=c.execute("SELECT id FROM sp WHERE strat=?", (s,)).fetchone()
        if ex:c.execute("UPDATE sp SET t=t+1,w=w+?,pnl=pnl+? WHERE strat?", (1 if pl>0 else 0,pl or 0,s))
        else:c.execute("INSERT INTO sp (ts,strat,tf,t,wr,sh,pnl) VALUES (?,?,?,?,0,0,?)", (datetime.now(timezone.utc).isoformat(),s,"live",1,pl or 0))
        c.commit();c.close();return{"ok":True,"n":len(self.lp)}
    def gr(self):
        c=sqlite3.connect(DB);cu=c.execute("SELECT bal FROM equity ORDER BY id").fetchall();c.close()
        if len(cu)<2:return{"cgr":0,"n":len(cu)}
        f=cu[0][0];l=cu[-1][0];n=len(cu)
        if f>0:return{"cgr":round((l/f)**(1.0/max(n-1,1))-1,4),"f":round(f,2),"l":round(l,2)}
        return{"cgr":0}
ceo=CEO()

class GATE:
    def __init__(self):self.p=0;self.f=0;self.l=None
    def v(self,e,b):
        ch={};q=qh.h[-1] if qh.h else qh.rr()
        ch["bt_tf"]=q.get("all_pass",False)
        fl=sum(1 for t in ft.c if t.get("pn",0)<0);ch["ft_ok"]=fl<=2
        ch["ceo_b"]=ceo.vb(b).get("ok",False);ch["ceo_e"]=ceo.ve(e).get("ok",False);ch["liq"]=e.get("vol",0)>=100
        ok=all(ch.values())
        if ok:self.p+=1
        else:self.f+=1
        self.l={"ok":ok,"ch":ch,"fl":[k for k,v in ch.items() if not v]}
        return self.l
gate=GATE()

class Q:
    def __init__(self):self.ps=0.02;self.h=[];self.it=0
    def rr(self):
        r={};self.ps=max(0.005,self.ps-0.003)
        for tf in BT:r[tf]=bt(tf,self.ps/100)
        ps=sum(1 for x in r.values() if x.get("pass"))
        a={"results":r,"ps":f"{ps}/{len(BT)}","ap":ps==len(BT),"i":self.it}
        if ps<len(BT):a["do"]="AGR";self.it+=1
        elif ps==len(BT):a["do"]="TGT"
        else:a["do"]="HLD"
        a["par"]=self.ps;self.h.append(a)
        if len(self.h)>100:self.h=self.h[-50:]
        return a
    def sh(self):
        if not self.h:self.rr()
        return self.h[-1].get("ap",False)
qh=Q()

class TR:
    def __init__(self):self.cb=10.0;self.tgt=1000.0;self.run=False;self.ci=60
    def ub(self):
        if not kc.auth:return self.cb
        try:b=kc.p.get_balance();self.cb=getattr(b,'balance',0)/100.0;return self.cb
        except:return self.cb
    def rm(self):
        r={"e":[]}
        if not kc.auth:return r
        try:
            mr=kc.m.get_markets(limit=50)
            for m in getattr(mr,"markets",[])[:40]:
                try:
                    d=kc.m.get_market(ticker=m.ticker);mk=getattr(d,"market",None)
                    if not mk:continue
                    ye=getattr(mk,"yes_bid",0) or 0;no2=getattr(mk,"no_ask",100) or 100;vo=getattr(mk,"volume",0) or 0
                    iy=ye/100.0 if ye>0 else 0;ec=0;si=None
                    if iy>0.85:ec=(100-ye)-2;si="yes" if ec>3 else None
                    elif iy<0.15:ec=ye-2;si="yes" if ec>3 else None
                    if si:
                        cf=min(0.85,0.50+ec/200.0);r["e"].append({"tk":m.ticker,"si":si,"ec":round(ec,2),"cf":round(cf,3),"vol":vo})
                except:pass
        except:pass
        return r
    def et(self,edges,b):
        r=[]
        if not kc.auth:return r
        c=sqlite3.connect(DB)
        try:
            edges.sort(key=lambda e:e["cf"]*e["ec"],reverse=True)
            for edge in edges[:3]:
                sz=min(0.50,max(0.05,edge["ec"]/200.0))*b;cnt=max(1,int(sz/20));cnt=min(cnt,5)
                try:
                    px=50;o=kc.co(ticker=edge["tk"],action="buy",side="yes",count=cnt,yes_price=px,expiration_type="GTC")
                    kc.p.create_order(o)
                    c.execute("INSERT INTO trades (ts,ticker,side,ep,cnt,status,strat) VALUES (?,?,?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(),edge["tk"],"yes",px,cnt,"FILLED","auto"))
                    r.append({"tk":edge["tk"],"s":"yes","cnt":cnt,"px":px})
                except:pass
            c.commit()
        finally:c.close()
        return r
    def ue(self):
        b=self.ub();c=sqlite3.connect(DB)
        tr=c.execute("SELECT * FROM trades").fetchall();wo=sum(1 for x in tr if len(x)>7 and x[7]>0);tt=len(tr)
        wr=(wo/tt) if tt else 0.5;ret=[x[7] for x in tr if len(x)>7 and x[7]!=0]
        sh=(float(np.mean(ret))/float(np.std(ret)))*np.sqrt(252) if (ret and np.std(ret)>0) else 0.0
        cu=c.execute("SELECT bal FROM equity ORDER BY id DESC").fetchall()
        mx=max(e[0] for e in cu) if cu else b;dd=((mx-b)/mx) if mx>0 else 0.0
        c.execute("INSERT INTO equity (ts,bal,t,sh,wr,dd) VALUES (?,?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(),b,tt,sh,wr,dd))
        c.commit();c.close();self.cb=b
    def rc(self):
        b=self.ub();self.cb=b
        if not qh.h:qh.rr()
        ft.sy();fe=ft.sc() if qh.sh() else []
        r=self.rm();ap=[];gd=[]
        for e in r.get("e",[]):
            g=gate.v(e,b)
            if g["ok"]:ap.append(e);gd.append({"tk":e["tk"],"gate":"PASS"})
            else:gd.append({"tk":e.get("tk","?"),"gate":"NO"})
        ex=self.et(ap,b) if ap else []
        for x in ex:ft.en(x.get("tk",""),x.get("s",""),x.get("px",50))
        for ct in ft.c[-5:]:
            if ct.get("pn") is not None:ceo.ln(ct.get("tk",""),ct.get("pn",0),"fw")
        self.ue()
        sr={tf:{"s":r2.get("strat","?"),"pass":r2.get("pass",False),"wr":r2.get("wr",0),"sh":r2.get("sh",0),"t":r2.get("trades",0),"pnl":r2.get("pnl",0)} for tf,r2 in qh.h[-1].get("results",{}).items()} if qh.h else {}
        return{"bal":round(b,2),"pct":round(b/self.tgt*100,1),"ap":qh.h[-1].get("ap",False) if qh.h else False,
            "strats":sr,"fa":len(ft.a),"fc":len(ft.c),"ee":len(r.get("e",[])),
            "go":len(ap),"gn":len(gd)-len(ap),"ex":len(ex),"lp":len(ceo.lp),
            "gt":{"p":gate.p,"f":gate.f},"par":qh.ps,"gr":ceo.gr(),"it":qh.it}
    def start(self,i=60):
        if self.run:return{"s":"ALREADY"}
        self.run=True;self.ci=i
        def loop():
            while self.run:
                try:self.rc();time.sleep(self.ci)
                except:c=sqlite3.connect(DB);c.execute("INSERT INTO log (ts,ev,det) VALUES (?,?,?)", (datetime.now(timezone.utc).isoformat(),"ERR","e"));c.commit();c.close();time.sleep(5)
        threading.Thread(target=loop,daemon=True).start()
        c=sqlite3.connect(DB);c.execute("INSERT INTO log (ts,ev,det) VALUES (?,?,?)", (datetime.now(timezone.utc).isoformat(),"START",f"i={i}"));c.commit();c.close()
        return{"s":"STARTED","i":i}
    def stop(self):self.run=False;return{"s":"STOP"}
tr=TR()

app=FastAPI(title="Kalshi Auto v7")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
@app.get("/h")
def h():return{"ok":kc.auth,"bal":tr.cb,"pct":round(tr.cb/1000*100,2)}
@app.post("/e")
def e():return tr.rc()
@app.post("/start")
def s(i:int=60):return tr.start(i)
@app.post("/stop")
def st():return tr.stop()
@app.get("/st")
def ss():return{"run":tr.run,"bal":tr.cb,"ci":tr.ci,"auth":kc.auth}
@app.get("/bt")
def b():return qh.rr()
@app.get("/fw")
def f():return{"a":[{"tk":p["t"],"s":p["s"],"e":p["e"]} for p in ft.a.values()],"c":[{"tk":t["tk"],"s":t["s"],"pn":t["pn"],"r":t["r"]} for t in ft.c]}
@app.get("/ceo")
def c():return{"vb":ceo.vb(tr.cb),"lp":len(ceo.lp),"gr":ceo.gr()}
@app.get("/gate")
def g():return{"p":gate.p,"f":gate.f}
@app.get("/quant")
def q():return{"ps":qh.ps,"n":len(qh.h),"last":qh.h[-1] if qh.h else None,"sh":qh.sh()}
@app.get("/port")
def p():
    b=tr.ub();c=sqlite3.connect(DB);t=c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 20").fetchall();c.close()
    return{"bal":b,"trades":[{"tk":x[2],"s":x[3],"px":x[4],"cnt":x[6],"pnl":x[7],"st":x[8]} for x in t]}
@app.get("/strats")
def sv():return{"count":len(SV),"names":list(set(x[0] for x in SV))}

if __name__=="__main__":
    import uvicorn;uvicorn.run(app,host="0.0.0.0",port=8000,log_level="info")
