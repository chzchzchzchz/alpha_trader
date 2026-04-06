const API=location.origin,REFRESH=3000
const $=id=>document.getElementById(id)

async function get(p){try{const r=await fetch(API+p);return r.ok?await r.json():null}catch{return null}}
const fmt=n=>"$"+(n||0).toFixed(2)
const fix=msg=>$("dot").className=!!msg?"dot live":"dot"

async function refresh(){
  const d=await get("/api/portfolio")
  if(!d)return fix(false)
  fix(true)$("eq").textContent=fmt(d.equity)
  $("pnl").className=d.pnl_today>=0?"pos":"neg";$("pnl").textContent=fmt(d.pnl_today)
  $("wr").textContent=(d.win_rate*100).toFixed(1)+"%"
  $("trc").textContent=d.trades?d.trades.length:0

  const px=$("px-body")
  if(d.live_prices){
    px.innerHTML=d.live_prices.map(p=>"<tr><td>"+p.ticker+"</td><td>"+fmt(p.price)+
      "</td><td class='"+(p.change>=0?"pos":"neg")+"'>"+(p.change*100).toFixed(2)+"%</td>"+
      "<td class='"+(p.sentiment=="bullish"?"pos":p.sentiment=="bearish"?"neg":"")+"'>"+p.sentiment+"</td></tr>").join("")
  }

  const tl=$("tl-body")
  if(d.trades){
    tl.innerHTML=d.trades.map(t=>"<tr><td>"+(t.ts||"").substring(0,19)+
      "</td><td>"+t.ticker+"</td><td class='"+(t.side=="yes"?"pos":t.side=="no"?"neg":"")+
      "'>"+t.side.toUpperCase()+"</td><td>"+t.size+"</td><td>"+t.result+
      '</td><td><button class="trade-btn" onclick="trade(\"'+t.ticker+'\",\"'+t.side+'\')">Replay</button></td></tr>').join("")
  }
}

async function refreshMkts(){
  const d=await get("/api/markets")
  if(!d)return
  const info=$("mkt-info")
  if(!d.markets||d.markets.length===0){
    info.textContent=(d.error?"Error: "+d.error:"No 15-min crypto markets on Kalshi demo right now")
    $("mkt-body").innerHTML=""
    return
  }
  info.textContent=d.markets.length+" markets found"
  $("mkt-body").innerHTML=d.markets.map(m=>"<tr><td>"+m.ticker+
    '</td><td>'+m.yes_bid+'c</td><td>'+m.no_ask+'c</td><td class="pos">-</td><td><button class="trade-btn" onclick="trade(\"'+m.ticker+'\",\"yes\')">Buy YES</button></td></tr>').join("")
}

async function refreshBT(){
  const d=await get("/api/backtest")
  if(!d)return
  $("bt-sym").textContent=d.best_symbol||"-"
  $("bt-wr").textContent=d.best_wr||"-"
  $("bt-sh").textContent=d.best_sharpe||"-"
  const v=$("bt-v");v.textContent=d.verdict||"-"
  v.className=d.verdict==="PASS"?"pass":d.verdict==="FAIL"?"fail":""
}

async function runBT(){
  $("bt-status").textContent="Running backtest..."
  $("bt-v").textContent="..."
  $("bt-status").className=""
  await fetch(API+"/api/run_backtest",{method:"POST"})
  setTimeout(()=>{refreshBT();$("bt-status").textContent="Backtest complete"},8000)
}

function trade(ticker,side){
  fetch(API+"/api/trade",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({ticker,side,qty:1})})
  setTimeout(refresh,1000)
}

setInterval(refresh,REFRESH);setInterval(refreshMkts,10000);setInterval(refreshBT,30000)
setInterval(()=>$("clock").textContent=new Date().toLocaleTimeString(),1000)
refresh();refreshMkts();refreshBT()
