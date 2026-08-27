export function createBridgeAdapter(global){
    const bridge = global.SmartImageAgentBridge;
    if(!bridge) throw new Error('Smart Canvas 图片桥接未就绪');
    return Object.freeze({
        context:() => bridge.getCanvasContext(),
        selection:() => bridge.getSelection?.() || [],
        subscribeSelection:listener => bridge.subscribeSelection?.(listener) || (() => {}),
        uploadReferences:files => bridge.uploadReferences(files),
        runImageTask:(run, plan, options) => bridge.runImageTask(run, plan, options),
        saveCanvas:() => bridge.saveCanvas(),
        focusResult:nodeId => bridge.focusNode?.(nodeId),
        saveToAssetLibrary:result => bridge.saveToAssetLibrary(result),
        canvasControls:bridge.canvasControls || {}
    });
}
