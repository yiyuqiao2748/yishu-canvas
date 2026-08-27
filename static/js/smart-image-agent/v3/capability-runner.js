export async function executeImageCapability({api, bridge, run, plan, isCancelled}){
    await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
        method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'running', progress_stage:'generating'})
    });
    const result = await bridge.runImageTask(run, plan, {isCancelled});
    if(isCancelled() || result?.cancelled) return null;
    await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
        method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'succeeded', progress_stage:'completed', result})
    });
    await bridge.saveCanvas();
    return result;
}
