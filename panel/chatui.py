"""Сторінка чату Кобзаря — ОДНА WKWebView-поверхня (26.09.2026).

Раніше чат був зшитий з чотирьох різнорідних шматків (NSTableView історії,
NSTextView вводу, WKWebView повідомлень, NSView-плашки) — кожен зі своїми
шрифтами/відступами, тому й виглядав «зібраним з різного». Тепер уся поверхня —
одна сторінка: історія, шапка, стрічка, ввід, меню @ і команд, картки задач доповнень.

Python → JS: виклики функцій нижче (setHist, setHead, loadMsgs, aiAppend…).
JS → Python: webkit.messageHandlers.chat.postMessage(JSON {a: дія, …}) +
імена copy/speak/regen/open/ext (їх обробник у panel.py).
"""

_PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{
  --accent:__ACCENT__;
  --text:#1c1c1e; --muted:#6e6e73; --faint:#a1a1a6;
  --side:var(--card); --line:rgba(0,0,0,.08); --hover:rgba(0,0,0,.045);
  --sel:rgba(0,0,0,.075); --ubg:rgba(0,0,0,.055); --code:rgba(0,0,0,.05);
  --field:rgba(255,255,255,.62); --pop:rgba(250,250,252,.97); --popline:rgba(0,0,0,.08);
  --card:rgba(255,255,255,.6); --veil:rgba(255,255,255,.74); --edge:inset 0 1px 0 rgba(255,255,255,.75);
  --drop:0 10px 28px -16px rgba(20,20,30,.28);
  --ok:#3a9a5b; --info:#3b7fc4; --warn:#c1822a; --bad:#c2453d;
}
:root.dark{
  --text:#ececee; --muted:#9a9aa0; --faint:#6b6b70;
  --side:var(--card); --line:rgba(255,255,255,.085); --hover:rgba(255,255,255,.05);
  --sel:rgba(255,255,255,.09); --ubg:rgba(255,255,255,.075); --code:rgba(255,255,255,.06);
  --field:rgba(255,255,255,.065); --pop:rgba(40,40,44,.97); --popline:rgba(255,255,255,.1);
  --card:rgba(255,255,255,.055); --veil:rgba(30,30,33,.66); --edge:inset 0 1px 0 rgba(255,255,255,.07);
  --drop:0 12px 30px -16px rgba(0,0,0,.55);
  --ok:#5bb97a; --info:#6aa6e0; --warn:#dca24d; --bad:#e0685f;
}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{height:100%;overflow:hidden;background:transparent;color:var(--text);
  font:13.5px/1.6 -apple-system,"SF Pro Text",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;-webkit-user-select:none;cursor:default;}
button{font:inherit;color:inherit;background:none;border:0;cursor:default;}
svg{width:16px;height:16px;flex:none;stroke:currentColor;fill:none;stroke-width:1.75;
  stroke-linecap:round;stroke-linejoin:round;}
#app{display:grid;grid-template-columns:220px minmax(0,1fr);height:100%;}

/* ── історія ── */
#side{background:var(--side);border:1px solid var(--line);border-radius:12px;margin:8px 0 8px 8px;
  box-shadow:var(--edge);overflow:hidden;display:flex;
  flex-direction:column;min-height:0;}
#newc{margin:14px 12px 8px;display:flex;align-items:center;gap:8px;padding:7px 10px;
  border-radius:8px;border:1px solid var(--line);color:var(--text);
  transition:background .15s,transform .1s;}
#newc:hover{background:var(--hover);} #newc:active{transform:scale(.98);}
#hist{flex:1 1 0;min-height:0;overflow-y:auto;overflow-x:hidden;padding:2px 8px 14px;
  -webkit-mask-image:linear-gradient(to bottom,#000 calc(100% - 16px),transparent);
  mask-image:linear-gradient(to bottom,#000 calc(100% - 16px),transparent);}
#hist::-webkit-scrollbar{width:6px;} #hist::-webkit-scrollbar-track{background:transparent;}
#hist::-webkit-scrollbar-thumb{background:transparent;border-radius:3px;}
#hist:hover::-webkit-scrollbar-thumb{background:var(--sel);}
#newc{flex:none;}
.sdiv{flex:none;height:1px;margin:2px 14px 10px;background:var(--line);}
#clrAll{margin:0 12px 12px;display:flex;align-items:center;gap:8px;padding:7px 10px;white-space:nowrap;
  border-radius:8px;border:1px solid color-mix(in srgb,var(--bad) 28%,var(--line));
  color:color-mix(in srgb,var(--bad) 72%,var(--muted));
  transition:background .15s,color .15s,border-color .15s,transform .1s;flex:none;min-width:0;text-align:left;}
#clrAll span{min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
#clrAll:hover{background:color-mix(in srgb,var(--bad) 9%,transparent);color:var(--bad);
  border-color:color-mix(in srgb,var(--bad) 55%,var(--line));}
#clrAll:active{transform:scale(.98);}
#clrAll.sure{color:#fff;background:var(--bad);border-color:var(--bad);}
.grp{font-size:11px;color:var(--faint);padding:12px 8px 4px;}
.hrow{position:relative;display:flex;align-items:center;border-radius:7px;padding:6px 8px;
  color:var(--muted);transition:background .12s;}
.hrow:hover{background:var(--hover);color:var(--text);}
.hrow.on{background:var(--sel);color:var(--text);}
.hrow .ht{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.hrow .hm{opacity:0;padding:2px;border-radius:5px;color:var(--muted);}
.hrow:hover .hm,.hrow.on .hm{opacity:1;} .hm:hover{background:var(--hover);color:var(--text);}
.hrow input{flex:1;min-width:0;font:inherit;color:var(--text);background:var(--field);
  border:1px solid var(--accent);border-radius:5px;padding:1px 6px;outline:none;}
.menu{position:fixed;z-index:50;min-width:170px;width:max-content;background:var(--pop);
  border:1px solid var(--popline);border-radius:9px;padding:4px;
  -webkit-backdrop-filter:blur(22px) saturate(1.6);backdrop-filter:blur(22px) saturate(1.6);
  box-shadow:var(--edge),0 10px 30px -12px rgba(0,0,0,.35);}
.menu button{display:flex;width:100%;gap:8px;align-items:center;padding:6px 8px;border-radius:6px;
  text-align:left;white-space:nowrap;}
.menu button:hover{background:var(--hover);} .menu .danger{color:var(--bad);}

/* ── основна колонка ── */
#main{position:relative;min-width:0;min-height:0;}
#head{position:absolute;top:0;left:0;right:0;z-index:2;display:flex;align-items:center;gap:10px;
  padding:12px 24px;min-height:48px;}   /* 26.09: без плити — верх і так гасне маскою #scroll */
#title{font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-right:auto;}
#chips{display:flex;gap:6px;align-items:center;flex-wrap:nowrap;overflow:hidden;min-width:0;flex:0 1 auto;}
#title{flex:1 1 0;min-width:96px;}
.chip{display:inline-flex;align-items:center;gap:6px;padding:1px 9px;border-radius:999px;
  background:transparent;border:1px solid var(--line);font-size:11.5px;line-height:1.55;
  color:var(--muted);white-space:nowrap;min-width:0;flex:0 1 auto;}   /* 30.09: статус, не повідомлення — без сірої заливки, як у бульбашки юзера */
.chip .ct{min-width:0;overflow:hidden;text-overflow:ellipsis;}
.chip .dot{flex:none;} .chip.more{flex:none;color:var(--faint);padding:1px 7px;}
.dot{width:6px;height:6px;border-radius:50%;flex:none;}
.dot.green{background:var(--ok);} .dot.blue{background:var(--info);}
.dot.orange{background:var(--warn);} .dot.gray{background:var(--faint);}
.dot.pulse{animation:pl 1.6s ease-in-out infinite;}
@keyframes pl{50%{opacity:.35;}}
.hmsg{flex:0 1 auto;padding:1px 2px;background:transparent;
  font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;}
.btn{padding:4px 12px;border-radius:7px;border:1px solid var(--line);font-size:12px;white-space:nowrap;flex:none;}
.btn:hover{background:var(--hover);} .btn:active{transform:scale(.98);}
.btn.pri{background:var(--accent);border-color:transparent;color:#fff;}
.btn.pri:hover{filter:brightness(1.07);}

#scroll{position:absolute;inset:0;overflow-y:auto;
  -webkit-mask-image:linear-gradient(to bottom,transparent 44px,#000 78px,#000 calc(100% - var(--fh,80px)),transparent calc(100% - var(--fh,80px)/3));
  mask-image:linear-gradient(to bottom,transparent 44px,#000 78px,#000 calc(100% - var(--fh,80px)),transparent calc(100% - var(--fh,80px)/3));}
#log{max-width:760px;margin:0 auto;padding:72px 24px calc(var(--fh,80px) + 8px);display:flex;flex-direction:column;gap:18px;}
.msg{-webkit-user-select:text;cursor:auto;animation:in .28s cubic-bezier(.16,1,.3,1);}
@keyframes in{from{opacity:0;transform:translateY(4px);}}
.msg.user{align-self:flex-end;max-width:78%;background:var(--ubg);padding:8px 14px;
  border-radius:14px 14px 4px 14px;white-space:pre-wrap;overflow-wrap:anywhere;}
.msg.user .at{color:var(--accent);}
.msg.ai{max-width:100%;}
.meta{font-size:11px;color:var(--faint);margin-bottom:3px;display:flex;align-items:center;gap:6px;}
.body{overflow-wrap:anywhere;}
.body p{margin:0 0 9px;} .body p:last-child{margin:0;}
.body pre{position:relative;background:var(--code);padding:11px 13px;border-radius:9px;
  overflow-x:auto;margin:9px 0;}
.body code{font:12.5px/1.5 "SF Mono",ui-monospace,monospace;}
.body pre code{white-space:pre;}
.body :not(pre)>code{background:var(--code);padding:1px 5px;border-radius:4px;}
.body h2,.body h3{margin:12px 0 4px;font-size:1.02em;font-weight:600;}
.body ul,.body ol{margin:6px 0;padding-left:20px;} .body li{margin:2px 0;}
.body li>ul,.body li>ol{margin:2px 0 3px;}
.kbl{margin-top:6px;font-size:11.5px;color:var(--faint);}
.kbl .kbt{display:inline-flex;align-items:center;gap:5px;padding:2px 6px 2px 4px;margin-left:-4px;border-radius:6px;color:var(--faint);}
.kbl button.kbt:hover{background:var(--hover);color:var(--muted);}
.kbl svg{width:12px;height:12px;} .kbl .chev{transition:transform .15s;} .kbl.open .chev{transform:rotate(90deg);}
.kbl .kbs{display:none;flex-wrap:wrap;gap:4px 6px;margin-top:4px;}
.kbl.open .kbs{display:flex;}
.kbl .kbs button,.kbl .kbs span{padding:1px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted);
  max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.kbl .kbs button:hover{background:var(--hover);color:var(--text);}
.body a{color:var(--accent);text-decoration:none;} .body a:hover{text-decoration:underline;}
.body strong{font-weight:600;}
.acts{display:flex;gap:2px;margin-top:4px;opacity:0;transition:opacity .15s;-webkit-user-select:none;}
.msg.ai:hover .acts,.msg.ai:last-child .acts{opacity:1;}
.act{display:inline-flex;align-items:center;gap:5px;padding:3px 7px;border-radius:6px;
  color:var(--faint);font-size:11.5px;}
.act:hover{background:var(--hover);color:var(--text);} .act svg{width:13px;height:13px;}
.typing{display:inline-flex;gap:4px;padding:6px 0;}
.typing i{width:5px;height:5px;border-radius:50%;background:var(--faint);animation:bo 1.2s infinite;}
.typing i:nth-child(2){animation-delay:.15s;} .typing i:nth-child(3){animation-delay:.3s;}
@keyframes bo{0%,80%,100%{opacity:.3;transform:translateY(0);}40%{opacity:1;transform:translateY(-2px);}}
.hit{padding:8px 0;border-bottom:1px solid var(--line);} .hit:last-child{border:0;}
.hit .hk{color:var(--accent);font-weight:500;} .hit .hx{color:var(--muted);white-space:pre-wrap;}
.note{align-self:center;font-size:12px;color:var(--faint);padding:2px 10px;}
/* 26.09: медіа у відповідях — картинка/відео/файл-чіп */
.media-img{max-width:100%;max-height:min(70vh,560px);object-fit:contain;border-radius:10px;display:block;margin:6px 0;cursor:pointer;}
.media-vid{max-width:100%;border-radius:10px;display:block;margin:6px 0;}
.filechip{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;margin:4px 0;
 border-radius:8px;border:1px solid var(--line);background:var(--ubg);color:var(--text);
 font-size:12.5px;cursor:pointer;font-family:inherit;}
.filechip:hover{background:var(--hover);}
.filechip svg{width:14px;height:14px;flex:0 0 auto;fill:none;stroke:currentColor;stroke-width:2;}
/* 26.09: довгі відповіді — згортаємо, щоб стрічка не летіла на екран */
.body.clamp{max-height:320px;overflow:hidden;
  -webkit-mask-image:linear-gradient(to bottom,#000 calc(100% - 96px),transparent);
  mask-image:linear-gradient(to bottom,#000 calc(100% - 96px),transparent);}
.clampToggle{display:inline-flex;align-items:center;gap:4px;margin-top:6px;padding:3px 11px;
  border-radius:999px;background:var(--ubg);color:var(--muted);font-size:12px;cursor:default;
  transition:background .15s,color .15s;}
.clampToggle:hover{background:var(--hover);color:var(--text);} .clampToggle:active{transform:scale(.98);}

#empty{max-width:760px;margin:0 auto;padding:calc(12vh + 48px) 24px 0;}
#empty h3{font-size:17px;font-weight:500;margin-bottom:4px;}
#empty p{color:var(--muted);margin-bottom:16px;}
.sug{display:flex;flex-direction:column;gap:6px;align-items:flex-start;}
.sug button{display:flex;gap:10px;align-items:baseline;padding:6px 10px;border-radius:8px;
  border:1px solid var(--line);text-align:left;}
.sug button:hover{background:var(--hover);}
.sug b{color:var(--accent);font-weight:500;font-family:"SF Mono",ui-monospace,monospace;font-size:12px;}
.sug span{color:var(--muted);font-size:12.5px;}

/* ── ввід ── */
#foot{position:absolute;left:0;right:0;bottom:0;z-index:2;padding:6px 24px 16px;}
#compose{position:relative;max-width:760px;margin:0 auto;border:1px solid var(--line);
  border-radius:14px;background:var(--field);box-shadow:var(--edge),var(--drop);
  -webkit-backdrop-filter:blur(24px) saturate(1.6);backdrop-filter:blur(24px) saturate(1.6);
  transition:border-color .15s,box-shadow .15s;}
#compose.focus{border-color:color-mix(in srgb,var(--accent) 55%,transparent);
  box-shadow:var(--edge),var(--drop),0 0 0 3px color-mix(in srgb,var(--accent) 14%,transparent);}
#atts{display:none;flex-wrap:wrap;gap:8px;padding:11px 12px 0;}
#atts.has{display:flex;}
.att{position:relative;display:inline-flex;align-items:center;gap:6px;max-width:190px;padding:5px 9px 5px 8px;
  border-radius:9px;border:1px solid var(--line);background:var(--ubg);font-size:12px;color:var(--text);}
.att.img{padding:0;border:0;background:none;}
.att img{width:54px;height:54px;object-fit:cover;border-radius:9px;border:1px solid var(--line);display:block;}
.att .nm{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.att svg{width:14px;height:14px;color:var(--muted);fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;}
.att .sz{color:var(--faint);font-size:11px;flex:none;}
.att .x{position:absolute;top:-6px;right:-6px;width:18px;height:18px;border-radius:50%;background:var(--pop);
  border:1px solid var(--popline);display:grid;place-items:center;color:var(--muted);padding:0;}
.att .x:hover{color:var(--bad);} .att .x svg{width:10px;height:10px;stroke-width:2.4;color:inherit;}
#compose.drop{border-color:var(--accent);box-shadow:var(--edge),var(--drop),0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent);}
.uatt{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-start;margin-bottom:6px;white-space:normal;}
.uatt:last-child{margin-bottom:0;}
.uatt img{max-width:190px;max-height:150px;border-radius:9px;display:block;cursor:pointer;}
.uatt .filechip{margin:0;background:var(--field);}
.uatt .filechip.gone{opacity:.55;cursor:default;text-decoration:line-through;}
/* 30.09: картки файлів — іконка за типом, імʼя, розмір, кнопки; текст розгортається прямо в чаті */
.fcard{display:block;max-width:100%;margin:6px 0;border:1px solid var(--line);border-radius:12px;
  background:var(--card);padding:9px 11px;-webkit-user-select:none;text-align:left;white-space:normal;}
.msg.user .fcard{background:var(--field);margin:0;}
.fhead{display:flex;align-items:center;gap:10px;min-width:0;}
.fic{flex:none;width:34px;height:34px;border-radius:9px;background:var(--ubg);display:grid;place-items:center;color:var(--muted);}
.fic svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;}
.ft{min-width:0;display:flex;flex-direction:column;}
.ft b{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.ft i{font-style:normal;font-size:11.5px;color:var(--faint);}
.fcard.gone .ft b{text-decoration:line-through;opacity:.6;}
.fact{display:flex;flex-wrap:wrap;gap:2px 4px;margin-top:5px;-webkit-user-select:none;}
.fhead+.fact{margin-top:8px;}
.fact button{padding:2px 8px;border-radius:6px;font-size:11.5px;color:var(--muted);border:1px solid transparent;}
.fact button:hover{background:var(--hover);color:var(--text);}
.fmedia{display:block;margin:6px 0;max-width:100%;}
.fmedia .fact{margin-top:3px;}
.fmedia img,.fmedia video{cursor:pointer;}
.msg.user .fmedia{margin:0;}
.fcard video{max-width:100%;border-radius:9px;display:block;margin:0 0 8px;}
.fcard audio{width:100%;display:block;margin:0 0 8px;}
.fprev{display:none;margin-top:8px;border-top:1px solid var(--line);padding-top:8px;-webkit-user-select:text;}
.fprev.on{display:block;}
.fprev pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto;margin:0;
  font:12px/1.5 "SF Mono",ui-monospace,monospace;}
.fprev .body{max-height:420px;overflow:auto;}
.fprev .fwait,.fprev .fnote{color:var(--faint);font-size:11.5px;}
.note.warn{color:var(--warn);max-width:560px;text-align:center;}
#inp{display:block;overflow-y:hidden;width:100%;resize:none;border:0;outline:none;background:transparent;color:var(--text);
  font:inherit;line-height:1.5;padding:11px 14px 4px;max-height:200px;min-height:24px;-webkit-user-select:text;}
#inp::placeholder{color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
#bar{display:flex;align-items:center;gap:2px;padding:4px 6px 6px 8px;}
.tg{display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border-radius:7px;color:var(--faint);white-space:nowrap;flex:none;
  font-size:12px;transition:background .12s,color .12s;}
.tg:hover{background:var(--hover);color:var(--text);}
.tg.on{color:var(--accent);background:color-mix(in srgb,var(--accent) 11%,transparent);}
.tg .tl{display:none;} .tg.on .tl{display:inline;}
#hint{margin-left:auto;margin-right:8px;font-size:11px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;}
#send{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;background:var(--accent);
  border:1px solid transparent;color:#fff;transition:transform .1s,filter .15s,background .15s,color .15s,border-color .15s;}
#send:hover{filter:brightness(1.08);} #send:active{transform:scale(.94);}
#send.idle{background:transparent;border-color:var(--line);color:var(--faint);}
#send.stop{background:var(--accent);color:#fff;}    /* 30.09: та сама форма й колір, що «надіслати»; змінюється лише значок */
#send.stop svg rect{stroke:none;}
#ac{position:absolute;left:0;right:0;bottom:calc(100% + 6px);background:var(--pop);
  border:1px solid var(--popline);border-radius:10px;padding:4px;display:none;
  -webkit-backdrop-filter:blur(22px) saturate(1.6);backdrop-filter:blur(22px) saturate(1.6);
  box-shadow:var(--edge),0 12px 32px -14px rgba(0,0,0,.35);max-height:260px;overflow-y:auto;}
#ac.open{display:block;}
.ai-row{display:flex;gap:12px;padding:6px 10px;border-radius:7px;align-items:baseline;}
.ai-row.on{background:var(--hover);}
.ai-row b{min-width:92px;color:var(--accent);font-weight:500;font-family:"SF Mono",ui-monospace,monospace;font-size:12px;}
.ai-row span{color:var(--muted);font-size:12.5px;}
::-webkit-scrollbar{width:8px;} ::-webkit-scrollbar-thumb{background:var(--ubg);border-radius:4px;}
/* вузьке вікно: спершу звужуємо історію, ховаємо лише зовсім тісно (стоїть у кінці — щоб не перебивалось) */
@media (max-width:760px){#app{grid-template-columns:184px minmax(0,1fr);} #hint{display:none;} #send{margin-left:auto;}
 #title{display:none;} #chips{margin-left:auto;}}   /* вузько: назву чату видно в історії, шапці віддаємо місце статусам */
@media (max-width:520px){#app{grid-template-columns:minmax(0,1fr);} #side{display:none;}}
</style></head>
<body><div id="app">
<aside id="side">
  <button id="newc"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>Нова розмова</button>
  <div id="hist"></div>
  <div class="sdiv"></div>
  <button id="clrAll" title="Перенести всі чати в архів (_архів у теці чатів)"></button>
</aside>
<main id="main">
  <header id="head"><div id="title"></div><div id="chips"></div></header>
  <div id="scroll"><div id="empty"></div><div id="log"></div></div>
  <div id="foot"><div id="compose">
    <div id="ac"></div>
    <div id="atts"></div>
    <textarea id="inp" rows="1" placeholder="Напиши запит"></textarea>
    <div id="bar">
      <button class="tg" id="tAtt" title="Додати файли: картинки, документи, відео (можна й перетягнути у вікно)">
        <svg viewBox="0 0 24 24"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg></button>
      <button class="tg" id="tAt" title="Команди (@ і /)">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/></svg></button>
      <button class="tg" id="tKb" title="База знань">
        <svg viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/></svg><span class="tl">База знань</span></button>
      <button class="tg" id="tSpk" title="Озвучувати відповіді">
        <svg viewBox="0 0 24 24"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a9 9 0 0 1 0 14"/></svg><span class="tl">Озвучка</span></button>
      <span id="hint">Enter — надіслати · Shift+Enter — рядок</span>
      <button id="send" class="idle" title="Надіслати"><svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg></button>
    </div>
  </div></div>
</main></div>
<script>
var $=function(s){return document.querySelector(s);};
if(__DARK__)document.documentElement.classList.add('dark');
var I={
 copy:'<svg viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
 spk:'<svg viewBox="0 0 24 24"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>',
 re:'<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>',
 dots:'<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>',
 web:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>',
 up:'<svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
 stop:'<svg viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor"/></svg>',
 edit:'<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
 eraser:'<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13"/></svg>',
 trash:'<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>',
 x:'<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
 book:'<svg viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/></svg>',
 chev:'<svg class="chev" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>',
 file:'<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>'};
var FI={
 txt:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
 code:'<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14"/>',
 sheet:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16M15 4v16"/>',
 slides:'<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
 zip:'<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4"/>',
 vid:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9l5 3-5 3z"/>',
 aud:'<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
 img:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/>',
 file:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>'};
var FK={md:'txt',txt:'txt',doc:'txt',pdf:'txt',csv:'sheet',sheet:'sheet',json:'code',code:'code',slides:'slides',zip:'zip',vid:'vid',aud:'aud',img:'img'};
var FL={img:'Картинка',vid:'Відео',aud:'Звук',md:'Markdown',txt:'Текст',csv:'Таблиця CSV',json:'JSON',code:'Код',pdf:'PDF',doc:'Документ',sheet:'Таблиця',slides:'Презентація',zip:'Архів',file:'Файл'};
var TXTK={md:1,txt:1,csv:1,json:1,code:1};
function qa(s){return String(s==null?'':s).replace(/"/g,'&quot;');}
function ficon(k){return '<svg viewBox="0 0 24 24">'+(FI[FK[k]||'file'])+'</svg>';}
/* кнопки під файлом: ті самі для картинки, відео й будь-якого документа */
function factHtml(prev){return '<span class="fact"><button type="button" data-fa="open">Відкрити</button>'+
 '<button type="button" data-fa="save">Зберегти оригінал</button><button type="button" data-fa="reveal">Показати у Finder</button>'+
 (prev?'<button type="button" data-fa="prev">Переглянути</button>':'')+'</span>';}
/* o = {name,path,kind,size,label,gone,prev,src}; src — адреса програвача для відео/звуку */
function fcard(o){var k=o.kind||'file',gone=!!o.gone,sub=(o.label||FL[k]||'Файл')+(o.size?' · '+o.size:'')+(gone?' · файл не знайдено':'');
 var pl='';if(!gone&&o.src){pl=k=='aud'?'<audio controls preload="metadata" src="'+qa(o.src)+'"></audio>':'<video controls preload="metadata" class="media-vid" src="'+qa(o.src)+'"></video>';}
 return '<span class="fcard'+(gone?' gone':'')+'" data-p="'+qa(o.path)+'" data-k="'+k+'">'+pl+
  '<span class="fhead"><span class="fic">'+ficon(k)+'</span><span class="ft"><b>'+esc(o.name||'')+'</b><i>'+esc(sub)+'</i></span></span>'+
  (gone?'':factHtml(!!o.prev))+(o.prev?'<span class="fprev"></span>':'')+'</span>';}
function imgMedia(o,src){return '<span class="fmedia" data-p="'+qa(o.path)+'" data-k="img"><img src="'+qa(src)+'" alt="'+qa(o.name)+'" title="'+qa(o.name)+'" loading="lazy" class="media-img" data-fa="open">'+factHtml(false)+'</span>';}
function post(o){try{webkit.messageHandlers.chat.postMessage(JSON.stringify(o));}catch(e){}}
function bridge(n,t){try{webkit.messageHandlers[n].postMessage(t);}catch(e){}}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
/* 30.09: списки одним проходом по рядках. Пункти через порожні рядки зливаються в ОДИН список,
   нумерація тримається за першим номером (<ol start>), вкладені пункти — за відступом. */
function mdLists(t){var L=t.split('\n'),out=[],i=0,IT=/^([ \t]*)([-*]|\d+\.) +(.*)$/,BL=/^\s*$/;
 while(i<L.length){if(!IT.test(L[i])){out.push(L[i]);i++;continue;}
  var items=[],j=i;
  while(j<L.length){var m=IT.exec(L[j]);
   if(m){items.push({ind:m[1].replace(/\t/g,'    ').length,ord:/\d/.test(m[2]),n:parseInt(m[2],10),t:m[3]});j++;continue;}
   if(BL.test(L[j])){var k=j;while(k<L.length&&BL.test(L[k]))k++;
    if(k<L.length&&(IT.test(L[k])||/^[ \t]+\S/.test(L[k]))){j=k;continue;}break;}
   if(/^[ \t]+\S/.test(L[j])){items[items.length-1].t+='<br>'+L[j].trim();j++;continue;}
   break;}
  out.push('',mdListHtml(items),'');i=j;}
 return out.join('\n');}
function mdListHtml(it){var h='',st=[];
 it.forEach(function(x){
  while(st.length&&st[st.length-1].ind>x.ind)h+='</li></'+(st.pop().ord?'ol':'ul')+'>';
  var top=st[st.length-1];
  if(top&&top.ind==x.ind){h+='</li>';if(top.ord!=x.ord){h+='</'+(top.ord?'ol':'ul')+'>';st.pop();top=null;}}
  if(!top||top.ind<x.ind){st.push({ind:x.ind,ord:x.ord});h+=x.ord?'<ol'+(x.n!=1?' start="'+x.n+'"':'')+'>':'<ul>';}
  h+='<li>'+x.t;});
 while(st.length)h+='</li></'+(st.pop().ord?'ol':'ul')+'>';
 return h;}
function md(t){var bl=[];
 t=t.replace(/```(\w*)\n?([\s\S]*?)```/g,function(m,l,c){bl.push('<pre><code>'+esc(c.replace(/\n$/,''))+'</code></pre>');return '¦'+(bl.length-1)+'¦';});
 t=esc(t);
 /* 26.09: медіа у відповідях — токени панелі ![[img:NAME|PATH]](data:...) /
    ![[vid:...]](kobzar-file://…) / ![[aud:...]] / ![[file:NAME|PATH]](file:тип,розмір), плюс «голі» посилання.
    30.09: кожен токен — картка з кнопками; у заглушку ¦n¦, щоб розмітка нижче не чіпала шлях. */
 var U=function(u){var m=/[?&]s=([^&]*)/.exec(u||'');return m?decodeURIComponent(m[1]):'';};
 t=t.replace(/!\[\[img:([^|\]]*)\|([^\]]*)\]\]\(([^)\s]*)\)/g,function(m,name,path,data){
   bl.push(imgMedia({name:name,path:path},data));return '¦'+(bl.length-1)+'¦';});
 t=t.replace(/!\[\[(vid|aud):([^|\]]*)\|([^\]]*)\]\]\(([^)\s]*)\)/g,function(m,k,name,path,src){
   bl.push(fcard({name:name,path:path,kind:k,src:src,size:U(src),prev:false}));return '¦'+(bl.length-1)+'¦';});
 t=t.replace(/!\[\[file:([^|\]]*)\|([^\]]*)\]\]\(file(?::([a-z]+),([^)]*))?\)/g,function(m,name,path,k,size){
   k=k||'file';bl.push(fcard({name:name,path:path,kind:k,size:size||'',prev:!!TXTK[k]}));return '¦'+(bl.length-1)+'¦';});
t=t.replace(/!\[([^\]]*)\]\((https?:[^)\s]+)\)/g,function(m,alt,url){
   return '<img src="'+url+'" alt="'+alt+'" loading="lazy" class="media-img">';});
 t=t.replace(/(^|[\s(])(https?:\/\/[^\s<>()]+\.(?:png|jpe?g|gif|webp|bmp))(?=[\s)]|$)/gi,function(m,pre,url){
   return pre+'<img src="'+url+'" alt="" loading="lazy" class="media-img">';});
 t=t.replace(/(^|[\s(])(https?:\/\/[^\s<>()]+\.(?:mp4|mov|webm|m4v))(?=[\s)]|$)/gi,function(m,pre,url){
   return pre+'<video controls class="media-vid" src="'+url+'"></video>';});
 t=t.replace(/`([^`\n]+)`/g,'<code>$1</code>');
 t=t.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
 t=t.replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>');
 t=t.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2">$1</a>');
 t=t.replace(/^### (.+)$/gm,'<h3>$1</h3>').replace(/^##? (.+)$/gm,'<h2>$1</h2>');
 t=mdLists(t);
 t=t.split(/\n{2,}/).map(function(p){p=p.trim();if(!p)return '';if(/^<(ul|ol|pre|h[23])/.test(p)||/^¦\d+¦$/.test(p))return p;return '<p>'+p.replace(/\n/g,'<br>')+'</p>';}).join('');
 return t.replace(/¦(\d+)¦/g,function(m,i){return bl[i];});}
document.addEventListener('click',function(e){var a=e.target.closest('a[href]');
 if(a){e.preventDefault();bridge('open',a.getAttribute('href'));}});
/* 26.09: системне контекстне меню WKWebView несе пункт «Reload», який на
   loadHTMLString-сторінці лишає чат порожнім НАЗАВЖДИ (нема куди «перезавантажити» —
   Python-бекап у webView:didFailNavigation: рятує, але краще не давати клікнути взагалі).
   Копіювання лишаємо: коли є виділений текст або клік у полі вводу/перейменування —
   не гасимо меню (там Copy/Paste з нативного WKWebView, чіпати не треба). */
document.addEventListener('contextmenu',function(e){
 var sel=(window.getSelection()||{}).toString();
 var inField=e.target.closest('#inp,textarea,input');
 if(sel||inField)return;
 e.preventDefault();
});

/* ── стрічка ── */
var log=$('#log'),sc=$('#scroll'),aiEl=null,aiRaw='',EXT=false,CMDS=[];
function nearEnd(){return sc.scrollHeight-sc.scrollTop-sc.clientHeight<120;}
function scr(force){if(force||nearEnd())sc.scrollTop=sc.scrollHeight;}
function showEmpty(on){var e=$('#empty');
 if(!on){e.innerHTML='';e.style.display='none';return;}
 e.style.display='block';
 var s=[['Порівняй','три способи пояснити рекурсію дітям'],['Склади','план уроку на 45 хвилин']];
 var x=(EXT&&typeof extSug=='function')?extSug(CMDS):null;     /* підказки додає доповнення, якщо воно є */
 if(x)s=(x.head||[]).concat(s,x.tail||[]);
 e.innerHTML='<h3>Про що поговоримо?</h3><p>Локальна модель відповідає без інтернету'+((EXT&&typeof extIntro=='string')?extIntro:'.')+'</p><div class="sug">'+
  s.map(function(x){return '<button data-v="'+esc(x[0]+' '+(x[0][0]=='@'?'':x[1]))+'"><b>'+esc(x[0])+'</b><span>'+esc(x[1])+'</span></button>';}).join('')+'</div>';
 e.querySelectorAll('button').forEach(function(b){b.onclick=function(){var v=b.getAttribute('data-v');
  inp.value=v.trim()+(v[0]=='@'?' ':'');inp.focus();grow();acUpdate();};});}
function clearAll(){log.innerHTML='';aiEl=null;aiRaw='';}
function empty(){clearAll();showEmpty(true);}
function el(cls,html){showEmpty(false);var d=document.createElement('div');d.className=cls;
 if(html!=null)d.innerHTML=html;log.appendChild(d);return d;}
function attHtml(att){if(!att||!att.length)return '';
 return '<div class="uatt">'+att.map(function(a){
  if(a.kind=='img'&&a.thumb&&!a.gone)return imgMedia(a,a.thumb);
  return fcard(a);}).join('')+'</div>';}
function addUser(t,att,fn){var d=el('msg user');var m=/^([@\/]\S+)([\s\S]*)$/.exec(t);
 var body=m?'<span class="at">'+esc(m[1])+'</span>'+esc(m[2]):esc(t);
 d.innerHTML=attHtml(att)+body;
 if(fn&&fn.length)attNote(fn,d);
 scr(true);return d;}
/* 30.09: чесний рядок ПІД повідомленням, одразу в момент відправки: що модель не побачила/не прочитала */
function attNote(lines,u){u=u||Array.prototype.filter.call(log.children,function(x){return x.classList.contains('user');}).pop();if(!u)return;
 var at=u;(lines||[]).forEach(function(l){var n=document.createElement('div');n.className='note warn';n.textContent=l;
  at.insertAdjacentElement('afterend',n);at=n;});scr(true);}
/* кнопки карток файлів і картинок (делегування: працює для живого показу й для історії) */
var FP={};
function fprevDraw(c,all){var o=FP[c.dataset.p],box=c.querySelector('.fprev');if(!box)return;
 if(!o||o.err){box.innerHTML='<span class="fnote">'+esc((o&&o.err)||'Не вдалося прочитати файл')+'</span>';return;}
 var txt=all?o.full:o.head,h=o.kind=='md'?'<div class="body">'+md(txt)+'</div>':'<pre>'+esc(txt)+'</pre>';
 var more=o.more?'<div class="fact"><button type="button" data-fa="'+(all?'less':'full')+'">'+(all?'Згорнути':'Показати все')+'</button>'+
  (all&&o.cut?'<span class="fnote">показано перші 200 КБ</span>':'')+'</div>':'';
 box.innerHTML=h+more;}
function filePrevSet(p,o){FP[p]=o;Array.prototype.forEach.call(document.querySelectorAll('.fcard[data-p]'),function(c){
 if(c.dataset.p==p&&c.querySelector('.fprev.on'))fprevDraw(c,false);});}
document.addEventListener('click',function(e){var b=e.target.closest('[data-fa]');if(!b)return;
 var c=b.closest('[data-p]');if(!c||c.classList.contains('gone'))return;e.preventDefault();
 var p=c.dataset.p,a=b.dataset.fa;
 if(a=='open')bridge('open',p);
 else if(a=='save')post({a:'fileSave',p:p});
 else if(a=='reveal')post({a:'fileReveal',p:p});
 else if(a=='prev'){var box=c.querySelector('.fprev');if(!box)return;
  if(box.classList.contains('on')){box.classList.remove('on');b.textContent='Переглянути';return;}
  box.classList.add('on');b.textContent='Сховати';
  if(FP[p])fprevDraw(c,false);else{box.innerHTML='<span class="fwait">Завантажую…</span>';post({a:'filePrev',p:p});}}
 else if(a=='full')fprevDraw(c,true);
 else if(a=='less')fprevDraw(c,false);});
function meta(m){return m?'<div class="meta">'+esc(m)+'</div>':'';}
function acts(d,raw,local){raw=String(raw).replace(/!\[\[(?:img|vid|aud|file):([^|\]]*)\|([^\]]*)\]\]\([^)]*\)/g,'$2');var a=document.createElement('div');a.className='acts';
 function b(ic,lbl,fn){var x=document.createElement('button');x.className='act';x.innerHTML=ic+'<span>'+lbl+'</span>';x.onclick=function(){fn(x);};a.appendChild(x);}
 b(I.copy,'Копіювати',function(x){bridge('copy',raw);var s=x.querySelector('span');s.textContent='Скопійовано';setTimeout(function(){s.textContent='Копіювати';},1200);});
 b(I.spk,'Озвучити',function(){bridge('speak',raw);});
 if(local)b(I.re,'Ще раз',function(){bridge('regen',raw);});
 d.appendChild(a);}
function clampCheck(d){var body=d&&d.querySelector('.body');if(!body)return;
 var old=d.querySelector('.clampToggle');if(old)old.remove();
 body.classList.remove('clamp');
 if(body.querySelector('img.media-img,video.media-vid,.fcard,.fmedia'))return;  /* 30.09: картинку не обрізаємо й не розмиваємо маскою */
 if(body.scrollHeight>320){
  var anchor=d.getBoundingClientRect().top;             // 26.09: якір — не смикати того, хто читає вище
  body.classList.add('clamp');
  if(!stick)sc.scrollTop+=(d.getBoundingClientRect().top-anchor);
  var btn=document.createElement('button');btn.className='clampToggle';btn.textContent='Показати повністю ▾';
  btn.onclick=function(){var on=body.classList.toggle('clamp');
   btn.textContent=on?'Показати повністю ▾':'Згорнути ▴';if(stick)scr(true);};
  body.insertAdjacentElement('afterend',btn);}}
function addAI(t,m,loc){var d=el('msg ai',meta(m)+'<div class="body">'+md(t)+'</div>');if(t)acts(d,t,loc===undefined?!m:!!loc);clampCheck(d);scr();return d;}
function aiStart(m){log.querySelectorAll('.msg.ai .acts').forEach(function(a){a.style.opacity='';});
 aiEl=el('msg ai',meta(m)+'<div class="body"><span class="typing"><i></i><i></i><i></i></span></div>');aiRaw='';scr(true);}
function aiAppend(c){if(!aiEl)aiStart('');aiRaw+=c;aiEl.querySelector('.body').innerHTML=md(aiRaw);scr();}
function aiEnd(){if(aiEl){if(!aiRaw)aiEl.querySelector('.body').innerHTML='<span style="color:var(--faint)">порожньо</span>';
 else acts(aiEl,aiRaw,true);}aiEl=null;aiRaw='';}
/* 26.09: clampCheck НЕ на aiEnd() навмисно — це локальний Ollama-стрім, згортання спец.
   лише для довгих готових відповідей (item 3), і на завершенні стріму воно
   смикало scrollTop ретроактивно (регресія «прокрутив угору — стрім не смикає вниз»). */
/* 30.09: «З бази знань: N уривків» — тиха стрічка під відповіддю; клік розгортає назви файлів.
   o = {n, src:[{n:імʼя, p:шлях або ''}]}; n=0 — нічого схожого; n<0 — пошук не спрацював. */
function kbPl(n){var a=n%10,b=n%100;return n+(a==1&&b!=11?' уривок':(a>=2&&a<=4&&(b<12||b>14)?' уривки':' уривків'));}
function kbLine(d,o){if(!d||!o)return;var old=d.querySelector('.kbl');if(old)old.remove();
 var x=document.createElement('div'),n=o.n||0,ic=I.book;x.className='kbl';
 if(n<=0){x.innerHTML='<span class="kbt">'+ic+(n<0?'Пошук по базі знань не спрацював':'У базі нічого схожого')+'</span>';}
 else{var src=(o.src||[]).map(function(s){return s.p?'<button type="button" data-p="'+esc(s.p)+'" title="Відкрити файл">'+esc(s.n)+'</button>':'<span>'+esc(s.n)+'</span>';}).join('');
  x.innerHTML='<button type="button" class="kbt" title="Показати, з яких файлів">'+ic+'З бази знань: '+kbPl(n)+I.chev+'</button><div class="kbs">'+src+'</div>';
  x.querySelector('.kbt').onclick=function(){x.classList.toggle('open');};
  x.querySelectorAll('.kbs button').forEach(function(b){b.onclick=function(){bridge('open',b.dataset.p);};});}
 var a=d.querySelector('.acts');d.insertBefore(x,a||null);}
function aiKb(o){if(aiEl)kbLine(aiEl,o);}
function aiHits(arr){if(!aiEl)aiStart('база знань');var h='',raw='';
 arr.forEach(function(it){var k=it.path?'<a class="hk" href="'+esc(it.path)+'">'+esc(it.tag)+'</a>':'<span class="hk">'+esc(it.tag)+'</span>';
  h+='<div class="hit">'+k+'<div class="hx">'+esc(it.text||'')+'</div></div>';raw+=it.tag+'\n'+(it.text||'')+'\n\n';});
 aiEl.querySelector('.body').innerHTML=h;aiRaw=raw;scr();}
function note(t){el('note').textContent=t;scr(true);}
function loadMsgs(arr){clearAll();if(!arr.length){showEmpty(true);return;}showEmpty(false);
 arr.forEach(function(m){if(m.r=='user')addUser(m.c,m.att,m.fn);else{var d=addAI(m.c,m.m||'',!m.x);if(m.kb)kbLine(d,m.kb);}});
 sc.scrollTop=sc.scrollHeight;}

/* ── історія ── */
var HIST=[],CUR=0,menuFor=-1;
function grpOf(ts){var d=new Date(ts*1000),n=new Date();var day=864e5;
 var t0=new Date(n.getFullYear(),n.getMonth(),n.getDate()).getTime();
 if(d>=t0)return 'Сьогодні';if(d>=t0-day)return 'Вчора';if(d>=t0-6*day)return 'Цього тижня';return 'Раніше';}
function setHist(items,cur){HIST=items;CUR=cur;renderHist();}
function renderHist(){closeMenu();var h=$('#hist'),g='',out='';
 HIST.forEach(function(it,i){var gg=grpOf(it.ts||0);if(gg!=g){g=gg;out+='<div class="grp">'+g+'</div>';}
  out+='<div class="hrow'+(i==CUR?' on':'')+'" data-i="'+i+'"><span class="ht">'+esc(it.t)+'</span><button class="hm" title="Дії">'+I.dots+'</button></div>';});
 h.innerHTML=out;
 h.querySelectorAll('.hrow').forEach(function(r){var i=+r.getAttribute('data-i');
  r.onclick=function(e){if(e.target.closest('.hm')){openMenu(r,i);return;}if(e.target.closest('.menu,input'))return;
   if(i!=CUR){CUR=i;renderHist();post({a:'sel',i:i});}};
  r.ondblclick=function(){rename(r,i);};});
 var on=h.querySelector('.hrow.on');if(on)on.scrollIntoView({block:'nearest'});}
function closeMenu(){var m=document.querySelector('.menu');if(m)m.remove();menuFor=-1;}
function openMenu(r,i){if(menuFor==i){closeMenu();return;}closeMenu();menuFor=i;
 var m=document.createElement('div');m.className='menu';
 m.innerHTML='<button data-a="ren">'+I.edit+'Перейменувати</button><button data-a="clr">'+I.eraser+'Очистити повідомлення</button><button data-a="del" class="danger">'+I.trash+'Видалити</button>';
 document.body.appendChild(m);var b=r.getBoundingClientRect(),w=m.offsetWidth,hh=m.offsetHeight;
 var x=Math.max(6,Math.min(b.right-4-w,innerWidth-w-6)),y=b.top+30;if(y+hh>innerHeight-6)y=Math.max(6,b.top-hh-2);
 m.style.left=x+'px';m.style.top=y+'px';
 m.querySelectorAll('button').forEach(function(b){b.onclick=function(e){e.stopPropagation();var a=b.getAttribute('data-a');
  if(a=='ren'){closeMenu();rename(r,i);}
  else if(a=='del'&&!b.dataset.sure){b.dataset.sure=1;b.lastChild.textContent='Точно видалити?';}
  else{closeMenu();post({a:a,i:i});}};});}
document.addEventListener('mousedown',function(e){if(!e.target.closest('.menu,.hm'))closeMenu();});
function rename(r,i){var sp=r.querySelector('.ht');var f=document.createElement('input');f.value=HIST[i].t;
 sp.replaceWith(f);f.focus();f.select();var done=false;
 function fin(ok){if(done)return;done=true;var t=f.value.trim();if(ok&&t&&t!=HIST[i].t){HIST[i].t=t;post({a:'ren',i:i,t:t});}renderHist();}
 f.onkeydown=function(e){if(e.key=='Enter')fin(true);if(e.key=='Escape')fin(false);};f.onblur=function(){fin(true);};}
$('#newc').onclick=function(){post({a:'new'});inp.focus();};
/* 26.09: «Очистити всі чати» — той самий двоклік-підтвердження, що й Видалити в меню рядка,
   лише на весь список; python-бік переносить файли в _архів (не hard-delete — зворотньо). */
var clrAll=$('#clrAll'),clrLbl='Очистити всі',clrSure='Точно очистити?',clrTO=null;
clrAll.innerHTML=I.trash+'<span>'+clrLbl+'</span>';
function clrAllReset(){clrAll.classList.remove('sure');clrAll.querySelector('span').textContent=clrLbl;clrAll.dataset.sure='';}
clrAll.onclick=function(){
 if(clrAll.dataset.sure){clearTimeout(clrTO);clrAllReset();post({a:'clearAll'});return;}
 clrAll.dataset.sure='1';clrAll.classList.add('sure');clrAll.querySelector('span').textContent=clrSure;
 clrTO=setTimeout(clrAllReset,3000);
};

/* ── шапка ── */
function setTitle(t){$('#title').textContent=t||'';}
function setHead(o){var c=$('#chips'),h='';
 (o.chips||[]).forEach(function(x){h+='<span class="chip'+(x[0]=='more'?' more':'')+'" title="'+esc(x[2]||'')+'">'+(x[0]=='more'?'':'<span class="dot '+x[0]+(x[0]=='blue'?' pulse':'')+'"></span>')+'<span class="ct">'+esc(x[1])+'</span></span>';});
 if(o.down)h='<span class="hmsg">Ollama не запущена</span><button class="btn pri" id="oll">Запустити</button>'+h;
 else if(!h&&o.msg)h='<span class="hmsg">'+esc(o.msg)+'</span>';
 c.innerHTML=h;var b=$('#oll');if(b)b.onclick=function(){b.textContent='Запускаю…';post({a:'ollama'});};}

/* ── ввід ── */
var inp=$('#inp'),GEN=false;
function grow(){var ph=inp.placeholder;inp.placeholder='';inp.style.height='auto';var h=inp.scrollHeight;inp.placeholder=ph;inp.style.height=Math.min(h,200)+'px';inp.style.overflowY=h>200?'auto':'hidden';syncSend();}
function syncSend(){var s=$('#send');if(GEN){s.className='stop';s.innerHTML=I.stop;s.title='Зупинити';}
 else{s.className=inp.value.trim()?'':'idle';s.innerHTML=I.up;s.title='Надіслати';}}
function setGen(on){GEN=!!on;syncSend();}
function send(){if(GEN){post({a:'stop'});return;}var t=inp.value.trim();
 if(!t){if(ATT.length)note('Напиши, що зробити з файлом');return;}
 inp.value='';grow();acHide();post({a:'send',t:t,att:ATT.map(function(x){return x.id;})});attClear();}
function inputRestore(t){if(!inp.value){inp.value=t;grow();}}
function focusInput(){inp.focus();}
$('#send').onclick=send;
/* 30.09: меню @ «блимало». Клік по кнопці @ спершу знімав фокус з поля (mousedown → blur), blur
   ставив таймер acHide на 120 мс, а сам клік уже відкривав меню й повертав фокус — таймер
   спрацьовував ПІСЛЯ відкриття й гасив його. Тепер: кнопки панелі не крадуть фокус, таймер
   скасовується поверненням фокусу й перевіряє, що фокус справді пішов, а клік поза меню закриває. */
var acTO=null;
inp.addEventListener('focus',function(){clearTimeout(acTO);$('#compose').classList.add('focus');});
inp.addEventListener('blur',function(){$('#compose').classList.remove('focus');clearTimeout(acTO);
 acTO=setTimeout(function(){if(document.activeElement!==inp)acHide();},120);});
$('#bar').addEventListener('mousedown',function(e){if(e.target.closest('button'))e.preventDefault();});
document.addEventListener('mousedown',function(e){if(AC.open&&!e.target.closest('#ac,#inp,#tAt'))acHide();});
document.addEventListener('keydown',function(e){if(e.key=='Escape'&&AC.open)acHide();});
inp.addEventListener('input',function(){grow();acUpdate();});
inp.addEventListener('keydown',function(e){
 if(AC.open){if(e.key=='ArrowDown'){acMove(1);e.preventDefault();return;}
  if(e.key=='ArrowUp'){acMove(-1);e.preventDefault();return;}
  if((e.key=='Enter'&&!e.shiftKey)||e.key=='Tab'){acAccept(AC.idx);e.preventDefault();return;}
  if(e.key=='Escape'){acHide();e.preventDefault();return;}}
 if(e.key=='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send();}});
function setToggles(o){$('#tKb').classList.toggle('on',!!o.kb);$('#tKb').title=o.kbTip||'База знань';
 $('#tSpk').classList.toggle('on',!!o.spk);}
$('#tKb').onclick=function(){post({a:'kb'});};
$('#tSpk').onclick=function(){post({a:'spk'});};
$('#tAt').onclick=function(){var v=inp.value;if(!v||'@/'.indexOf(v[0])<0)inp.value='@'+(v?' '+v:'');
 clearTimeout(acTO);inp.focus();inp.setSelectionRange(1,1);grow();acUpdate();};

/* ── вкладення (30.09): скріпка, перетягування, вставка ── */
var ATT=[],ATT_MAX=6,JS_MAX=25*1024*1024;
function attRender(){var b=$('#atts');b.classList.toggle('has',ATT.length>0);b.innerHTML='';
 ATT.forEach(function(a){var d=document.createElement('div');d.className='att'+(a.kind=='img'&&a.thumb?' img':'');
  d.title=a.name+(a.size?' · '+a.size:'');
  d.innerHTML=(a.kind=='img'&&a.thumb?'<img src="'+a.thumb+'" alt="">':ficon(a.kind)+'<span class="nm">'+esc(a.name)+'</span>'+(a.size?'<span class="sz">'+esc(a.size)+'</span>':''))+
   '<button class="x" title="Прибрати">'+I.x+'</button>';
  d.querySelector('.x').onclick=function(){ATT=ATT.filter(function(x){return x.id!=a.id;});post({a:'attDel',id:a.id});attRender();};
  b.appendChild(d);});
 grow();}
function attAdded(o){if(ATT.length>=ATT_MAX){post({a:'attDel',id:o.id});note('Не більше '+ATT_MAX+' файлів за раз');return;}
 ATT.push(o);attRender();inp.focus();}
function attClear(){ATT=[];attRender();}
function attTake(files){Array.prototype.forEach.call(files,function(f){
 if(f.size>JS_MAX){note('«'+f.name+'» завеликий для перетягування — додай його скріпкою');return;}
 var r=new FileReader();r.onload=function(){var s=String(r.result),i=s.indexOf(',');
  post({a:'attData',name:f.name||'вставлене',mime:f.type||'',data:s.slice(i+1)});};r.readAsDataURL(f);});}
$('#tAtt').onclick=function(){post({a:'attPick'});};
function hasFiles(e){var t=e.dataTransfer&&e.dataTransfer.types;return !!t&&Array.prototype.indexOf.call(t,'Files')>=0;}
['dragenter','dragover'].forEach(function(n){document.addEventListener(n,function(e){if(!hasFiles(e))return;
 e.preventDefault();$('#compose').classList.add('drop');});});
document.addEventListener('dragleave',function(e){if(e.relatedTarget==null)$('#compose').classList.remove('drop');});
document.addEventListener('drop',function(e){if(!hasFiles(e))return;e.preventDefault();$('#compose').classList.remove('drop');
 attTake(e.dataTransfer.files);});
inp.addEventListener('paste',function(e){var fs=e.clipboardData&&e.clipboardData.files;
 if(fs&&fs.length){e.preventDefault();var big=false;Array.prototype.forEach.call(fs,function(f){if(f.size>JS_MAX)big=true;});
  if(big)post({a:'attPaste'});else attTake(fs);}});   /* велике — Python читає файл із буфера сам (лише читає, не змінює) */
function dropHint(on){$('#compose').classList.toggle('drop',!!on);}

/* ── автодоповнення @/ ── */
var AC={open:false,idx:0,items:[]};
function acUpdate(){var head=inp.value.slice(0,inp.selectionStart);
 if(!head||'@/'.indexOf(head[0])<0||/\s/.test(head)){acHide();return;}
 var it=CMDS.filter(function(c){return c[0].indexOf(head)==0;});if(!it.length){acHide();return;}
 AC.items=it;AC.idx=AC.open?Math.min(AC.idx,it.length-1):0;AC.open=true;acRender();}
function acRender(){var a=$('#ac');a.classList.add('open');
 a.innerHTML=AC.items.map(function(c,i){return '<div class="ai-row'+(i==AC.idx?' on':'')+'" data-i="'+i+'"><b>'+esc(c[0])+'</b><span>'+esc(c[1])+'</span></div>';}).join('');
 a.querySelectorAll('.ai-row').forEach(function(r){r.onmousedown=function(e){e.preventDefault();acAccept(+r.getAttribute('data-i'));};});
 var on=a.querySelector('.on');if(on)on.scrollIntoView({block:'nearest'});}
function acMove(d){AC.idx=(AC.idx+d+AC.items.length)%AC.items.length;acRender();}
function acAccept(i){var tok=AC.items[i][0];var v=inp.value;var m=/^\S*\s*/.exec(v)[0];
 inp.value=tok+' '+v.slice(m.length);var p=tok.length+1;inp.setSelectionRange(p,p);acHide();grow();}
function acHide(){AC.open=false;$('#ac').classList.remove('open');}
var CMDSIG='';
function setCmds(a){var sg=JSON.stringify(a||[]);if(sg==CMDSIG)return;CMDSIG=sg;CMDS=a||[];if(AC.open)acUpdate();if(!log.children.length&&$('#empty').style.display!='none')showEmpty(true);}
function setBoot(o){EXT=!!o.ext;CMDS=o.cmds||[];CMDSIG=JSON.stringify(CMDS);$('#tAt').style.display=EXT?'':'none';
 inp.placeholder=(EXT&&typeof extPh=='string')?extPh:'Напиши запит';
 if(EXT&&typeof extTip=='string')$('#tAt').title=extTip;
 if(!log.children.length)showEmpty(true);grow();}
var stick=true;sc.addEventListener('scroll',function(){stick=nearEnd();},{passive:true});
grow();window.addEventListener('resize',function(){closeMenu();grow();if(stick)scr(true);});
(function(){var f=document.getElementById('foot');if(!f||!window.ResizeObserver)return;
 new ResizeObserver(function(){document.documentElement.style.setProperty('--fh',f.offsetHeight+'px');if(stick)scr(true);}).observe(f);})();
</script></body></html>"""


def page(dark, accent):
    """HTML сторінки чату під поточну тему й акцент (підставляються при кожному перезавантаженні)."""
    return _PAGE.replace("__DARK__", "true" if dark else "false").replace("__ACCENT__", accent)
