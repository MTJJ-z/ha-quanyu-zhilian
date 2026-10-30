/* Browser harness: real bundled panel, simulated HA service responses. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 const errors=[];
 page.on("pageerror",e=>errors.push(e.message));
 await page.setContent('<html lang="zh-CN"><body style="margin:0"><quanyu-zhilian-panel></quanyu-zhilian-panel></body></html>');
 await page.addScriptTag({path:path.join(__dirname,"../custom_components/quanyu_zhilian/frontend/panel.js")});
 await page.evaluate(()=>{
   window.mock={ready:true,failSend:false,calls:[],requests:[]};
   const profiles=[{id:"tcl",model:"客厅测试遥控器",brand:"TCL",category:"ACs",signal_count:3},
     {id:"tv",model:"电视测试遥控器",brand:"Example",category:"TVs",signal_count:1}];
   const source={profiles:"8901",signals:"301915",revision:"d126fb1b6f1e114c52b4a8c19839ea65e3a9c24d"};
   const fixture={id:"tcl",model:"客厅测试遥控器",brand:"TCL",path:"ACs/TCL/Example.ir",signals:[
     {index:0,name:"电源",cyd_sendable:true,limitation:null},
     {index:1,name:"温度 +",cyd_sendable:false,limitation:"RAW_LENGTH_NOT_SUPPORTED: 200"},
     {index:2,name:'<img src=x onerror=alert(1)>',cyd_sendable:false,limitation:"PARSED_PROTOCOL_NOT_SUPPORTED"},
   ]};
   document.querySelector("quanyu-zhilian-panel").hass={
     callWS:async(msg)=>{
       window.mock.requests.push(msg);
       if(msg.service==="ir_gateways")return {response:{gateways:[{gateway_id:"cyd_08a570f3af48",room:"客厅",online:window.mock.ready,ready:window.mock.ready,ir_send:true}]}};
       if(msg.service==="ir_search"){
         if(msg.service_data.query==="error")throw Error("模拟数据库错误");
         return {response:{profiles:msg.service_data.query==="missing"?[]:profiles,total:msg.service_data.query==="missing"?0:2,source}};
       }
       if(msg.service==="ir_inspect")return {response:{...fixture,id:msg.service_data.profile_id}};
       throw Error("Unexpected service");
     },
     callService:async(domain,service,data)=>{window.mock.calls.push({domain,service,data});if(window.mock.failSend)throw Error("RESULT_UNKNOWN: acknowledgement timeout");},
   };
 });
 const panel=page.locator("quanyu-zhilian-panel");
 await panel.locator(".remote").first().waitFor();
 assert.equal(await panel.locator("#gateway option").count(),1);
 await panel.locator(".remote").first().click();
 await panel.locator(".key").first().waitFor();
 assert.equal(await panel.locator(".key").count(),3);
 assert.equal(await panel.locator(".key:enabled").count(),1);
 assert.equal(await panel.locator("#keys img").count(),0,"untrusted signal text must not become HTML");
 await panel.locator(".key").first().click();
 await page.waitForFunction(()=>document.querySelector("quanyu-zhilian-panel").shadowRoot.querySelector("#notice").textContent.includes("CYD 已回执"));
 const calls=await page.evaluate(()=>window.mock.calls);
 assert.deepEqual(calls[0],{domain:"quanyu_zhilian",service:"ir_send",data:{gateway_id:"cyd_08a570f3af48",profile_id:"tcl",signal_index:0}});
 await panel.locator("#supported-only").check();
 assert.equal(await panel.locator(".key").count(),1);
 await page.evaluate(()=>{window.mock.failSend=true;});
 await panel.locator(".key").first().click();
 await page.waitForFunction(()=>document.querySelector("quanyu-zhilian-panel").shadowRoot.querySelector("#notice").textContent.includes("RESULT_UNKNOWN"));
 await page.evaluate(()=>{window.mock.ready=false;});
 await panel.locator("#refresh").click();
 await page.waitForFunction(()=>document.querySelector("quanyu-zhilian-panel").shadowRoot.querySelector("#gateway-status").textContent.includes("离线"));
 assert.equal(await panel.locator(".key:enabled").count(),0);
 await panel.locator("#query").fill("missing");
 await panel.locator("#search").click();
 await page.waitForFunction(()=>document.querySelector("quanyu-zhilian-panel").shadowRoot.querySelector("#count").textContent.includes("没有找到"));
 await panel.locator("#query").fill("error");
 await panel.locator("#search").click();
 await page.waitForFunction(()=>document.querySelector("quanyu-zhilian-panel").shadowRoot.querySelector("#notice").textContent.includes("模拟数据库错误"));
 await page.evaluate(()=>{window.mock.ready=true;window.mock.failSend=false;});
 await panel.locator("#refresh").click();
 await panel.locator("#query").fill("");
 await panel.locator("#search").click();
 await panel.locator(".remote").first().waitFor();
 await panel.locator("#supported-only").uncheck();
 await page.evaluate(()=>document.querySelector("quanyu-zhilian-panel").notice(""));
 fs.mkdirSync(path.join(__dirname,"../dist"),{recursive:true});
 await page.screenshot({path:path.join(__dirname,"../dist/ir-panel-desktop.png"),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(__dirname,"../dist/ir-panel-mobile.png"),fullPage:true});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),"no horizontal overflow on phone");
 assert.deepEqual(errors,[]);
 await browser.close();
 console.log("Panel browser checks passed: search, inspect, escaped content, send payload, error, offline, filtering and mobile layout.");
})().catch(error=>{console.error(error);process.exit(1);});
