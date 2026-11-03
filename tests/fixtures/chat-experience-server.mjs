// Synthetic API only; serves the production chat HTML and assets for UX checks.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const root=new URL('../../src/radhouse/chat/static/',import.meta.url);
export async function startChatFixture() {
  const requests=[];
  const turns=Array.from({length:12},(_,index)=>({seq:index+1,request_id:`fixture-${index}`,created_at:'2026-11-02T15:00:00Z',text:index===11?'Help me choose one useful next step.':`Planning note ${index+1}: make room for focused work.`,output:index===11?'## Start with one clear outcome\n\nChoose a small task you can finish today. **Keep the next step visible**, then come back when you are ready.\n\n- Write down the result you want.\n- Make room for one focused session.\n- Review what changed.\n\n```js\nconst nextStep = "Make a little progress";\n```':'A useful plan leaves room to think. Pick one concrete action, keep the context close, and return when you need it.',status:'completed',attachments:[]}));
  const catalog={schema:'radhouse.inference.v1',state:'available',engine:{id:'nemo',label:'Nemo'},engines:[{id:'nemo',label:'Nemo'},{id:'lucy',label:'Lucy'},{id:'custom:openai',label:'OpenAI'}],current_model:'local-model',models:[
    {id:'local-model',provider:'nemo',label:'Local model',available:true,thinking:{state:'unknown',choices:[],can_enable:false,can_disable:false}},
    {id:'local-model',provider:'lucy',label:'Local model',available:true,thinking:{state:'unknown',choices:[],can_enable:false,can_disable:false}},
    ...['gpt-6-astra','gpt-6.1-terra','gpt-6.1-sol'].map((id,i)=>({id,provider:'custom:openai',label:['GPT-6 Astra','GPT-6.1 Terra','GPT-6.1 Sol'][i],available:true,thinking:{state:'supported',choices:['low','medium','high','xhigh','max'],can_enable:false,can_disable:id==='gpt-6.1-terra'}}))]};
  const server=createServer(async(req,res)=>{
    const path=new URL(req.url,'http://localhost').pathname;
    const json=value=>{res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
    if(path==='/auth/session')return json({username:'synthetic-owner',csrf_token:'synthetic',features:{inference:true}});
    if(path==='/chat/inference')return json(catalog);
    if(path==='/chat/history'||path==='/chat/reply')return json({turns,older_before:null});
    if(path==='/chat/agent-profile')return json({schema:'radhouse.agent-profile.v1',revision:0,name:'',intro:'',theme:'hearthside',portrait:'ember',accent:'fern',surface:'paper',stateMotion:false,iconMotion:false});
    if(path==='/chat/messages'&&req.method==='POST'){
      let body='';for await(const chunk of req){body+=chunk;if(body.length>100000){res.writeHead(413);res.end();return;}}
      const data=JSON.parse(body);requests.push(data);const turn={...data,seq:turns.length+1,status:'completed',output:'Synthetic receipt: your message and selected thinking arrived together.',created_at:new Date().toISOString()};turns.push(turn);return json({turns,accepted_request_id:data.request_id});
    }
    if(path==='/chat/library')return json({files:[]});
    let file=path==='/'?'index.html':path.replace(/^\/(workspace-assets\/|workspace-vendor\/)?/,'');
    if(path.startsWith('/workspace-vendor/'))file='vendor/'+file;
    if(!/^[a-zA-Z0-9][a-zA-Z0-9_./-]*$/.test(file)||file.includes('..')){res.writeHead(404);res.end();return;}
    try{const body=await readFile(new URL(file,root));const ext=file.split('.').at(-1);res.writeHead(200,{'Content-Type':{html:'text/html',js:'text/javascript',css:'text/css',json:'application/json',webp:'image/webp'}[ext]||'application/octet-stream'});res.end(body);}catch{res.writeHead(404);res.end();}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  return {origin:'http://127.0.0.1:'+server.address().port,requests,turns,catalog,close:()=>new Promise(resolve=>server.close(resolve))};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){const fixture=await startChatFixture();console.log(fixture.origin);}
