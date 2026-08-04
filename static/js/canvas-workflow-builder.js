/* canvas-workflow-builder.js
   Built-in workflow templates. This module only builds node payloads; it never runs generation. */
(function(){
    'use strict';

    const IMAGE_PROVIDER = 'custom-api';
    const IMAGE_MODEL = 'nano-banana-2';
    const IMAGE_PRO_MODEL = 'nano-banana-pro';
    const VIDEO_PROVIDER = 'agnes-ai';
    const VIDEO_MODEL = 'agnes-video-v2.0';

    const BUILTIN_WORKFLOW_TEMPLATES = [
        {
            id:'text-to-image',
            name:'文生图',
            description:'提示词 → Nano Banana 生图节点',
            icon:'type',
            requiresImage:false,
            provider_id:IMAGE_PROVIDER,
            model:IMAGE_MODEL,
        },
        {
            id:'image-to-image',
            name:'图生图',
            description:'图片输入 → 提示词 → Nano Banana 生图节点',
            icon:'image-plus',
            requiresImage:true,
            provider_id:IMAGE_PROVIDER,
            model:IMAGE_MODEL,
        },
        {
            id:'image-to-video',
            name:'图生视频',
            description:'图片输入 → Agnes 视频节点',
            icon:'film',
            requiresImage:true,
            provider_id:VIDEO_PROVIDER,
            model:VIDEO_MODEL,
        },
    ];

    const templateById = new Map(BUILTIN_WORKFLOW_TEMPLATES.map(item => [item.id, item]));
    const processedOperationIds = new Set();
    const translationModes = {
        translate:'仅翻译',
        optimize:'专业优化'
    };

    function clone(value){
        return JSON.parse(JSON.stringify(value == null ? null : value));
    }

    function now(){
        return Date.now();
    }

    function operationId(templateId){
        return `workflow_builder_${templateId}_${now()}_${Math.random().toString(16).slice(2)}`;
    }

    function normalizePoint(point){
        return {
            x:Number(point?.x || 0),
            y:Number(point?.y || 0),
        };
    }

    function template(templateId){
        const found = templateById.get(String(templateId || ''));
        if(!found) throw new Error('unknown workflow template');
        return found;
    }

    function validateImage(templateItem, selectedImage){
        if(!templateItem.requiresImage) return null;
        if(!selectedImage || !selectedImage.url) throw new Error('selected image node required');
        return {
            url:selectedImage.url,
            name:selectedImage.name || 'selected-image',
            kind:selectedImage.kind || 'image',
            asset_uris:selectedImage.asset_uris || {},
        };
    }

    function workflowImage(templateItem, options){
        if(!templateItem.requiresImage) return null;
        if(options.allowEmptyImage && (!options.selectedImage || !options.selectedImage.url)) return null;
        return validateImage(templateItem, options.selectedImage || null);
    }

    function connection(id, from, to, kind='flow'){
        return {id, from, to, kind};
    }

    function classicPromptNode(id, point, text, title='Prompt'){
        return {id, type:'prompt', x:point.x, y:point.y, text:String(text || ''), title};
    }

    function classicImageNode(id, point, image){
        return {
            id,
            type:'image',
            x:point.x,
            y:point.y,
            url:image.url,
            name:image.name || 'selected-image',
            mediaKind:image.kind || 'image',
        };
    }

    function emptyClassicImageNode(id, point){
        return {
            id,
            type:'image',
            x:point.x,
            y:point.y,
            url:'',
            name:'Image input',
            mediaKind:'image',
        };
    }

    function classicGeneratorNode(id, point, model=IMAGE_MODEL){
        return {
            id,
            type:'generator',
            x:point.x,
            y:point.y,
            apiProvider:IMAGE_PROVIDER,
            model,
            ratio:'square',
            resolution:'2K',
            customRatio:'',
            customSize:'',
            customRatioWidth:'',
            customRatioHeight:'',
            customWidth:'',
            customHeight:'',
            count:1,
            inputs:[],
            running:false,
        };
    }

    function classicVideoNode(id, point){
        return {
            id,
            type:'video',
            x:point.x,
            y:point.y,
            apiProvider:VIDEO_PROVIDER,
            model:VIDEO_MODEL,
            duration:5,
            aspectRatio:'16:9',
            resolution:'',
            enhancePrompt:false,
            enableUpsample:false,
            watermark:false,
            cameraFixed:false,
            generateAudio:false,
            useFrameRoles:false,
            multimodal:true,
            tempShLinks:[],
            inputs:[],
            running:false,
        };
    }

    function smartPromptNode(id, point, text, title='Prompt'){
        return {
            id,
            type:'smart-prompt',
            x:point.x,
            y:point.y,
            w:316,
            h:240,
            title,
            text:String(text || ''),
            promptSeparator:';',
            promptSplitEnabled:false,
            llmEnabled:false,
            llmSystemEnabled:false,
            llmSystemPrompt:'You are a helpful prompt assistant.',
            llmInstruction:'',
            created_at:now(),
        };
    }

    function smartImageNode(id, point, images, title='Image', runSettings=null){
        const node = {
            id,
            type:'smart-image',
            x:point.x,
            y:point.y,
            title,
            images:images || [],
            created_at:now(),
        };
        if(runSettings) node.runSettings = runSettings;
        return node;
    }

    function emptySmartImageNode(id, point, title='Image input'){
        return smartImageNode(id, point, [], title);
    }

    function smartImageSettings(){
        return {
            engine:'api',
            apiKind:'image',
            provider_id:IMAGE_PROVIDER,
            model:IMAGE_MODEL,
            ratio:'square',
            resolution:'2K',
            count:1,
        };
    }

    function smartVideoSettings(){
        return {
            engine:'api',
            apiKind:'video',
            videoProvider:VIDEO_PROVIDER,
            videoModel:VIDEO_MODEL,
            videoDuration:5,
            videoAspect:'16:9',
            videoResolution:'',
            videoEnhancePrompt:false,
            videoEnableUpsample:false,
            videoWatermark:false,
            videoCameraFixed:false,
            videoGenerateAudio:false,
            videoMultimodal:true,
            videoUseFrameRoles:false,
        };
    }

    function buildClassicWorkflow(templateId, options={}){
        const item = template(templateId);
        const selectedImage = workflowImage(item, options);
        const point = normalizePoint(options.point);
        const op = options.operation_id || operationId(item.id);
        const promptText = options.prompt || (item.id === 'image-to-video' ? 'Describe the motion and camera movement for this image.' : 'Describe the image you want to create.');
        const nodes = [];
        const connections = [];
        if(item.id === 'text-to-image'){
            nodes.push(classicPromptNode(`${op}_prompt`, {x:point.x, y:point.y}, promptText, '英文提示词'));
            nodes.push(classicGeneratorNode(`${op}_generator`, {x:point.x + 360, y:point.y}, IMAGE_MODEL));
            connections.push(connection(`${op}_c_prompt_generator`, `${op}_prompt`, `${op}_generator`));
        } else if(item.id === 'image-to-image'){
            nodes.push(selectedImage ? classicImageNode(`${op}_source`, {x:point.x, y:point.y}, selectedImage) : emptyClassicImageNode(`${op}_source`, {x:point.x, y:point.y}));
            nodes.push(classicPromptNode(`${op}_prompt`, {x:point.x + 340, y:point.y}, promptText, '英文提示词'));
            nodes.push(classicGeneratorNode(`${op}_generator`, {x:point.x + 700, y:point.y}, IMAGE_MODEL));
            connections.push(connection(`${op}_c_source_generator`, `${op}_source`, `${op}_generator`));
            connections.push(connection(`${op}_c_prompt_generator`, `${op}_prompt`, `${op}_generator`));
        } else if(item.id === 'image-to-video'){
            nodes.push(selectedImage ? classicImageNode(`${op}_source`, {x:point.x, y:point.y}, selectedImage) : emptyClassicImageNode(`${op}_source`, {x:point.x, y:point.y}));
            nodes.push(classicPromptNode(`${op}_prompt`, {x:point.x + 340, y:point.y}, promptText, '英文运镜提示词'));
            nodes.push(classicVideoNode(`${op}_video`, {x:point.x + 700, y:point.y}));
            connections.push(connection(`${op}_c_source_video`, `${op}_source`, `${op}_video`));
            connections.push(connection(`${op}_c_prompt_video`, `${op}_prompt`, `${op}_video`));
        }
        return {format:'infinite-canvas-workflow', operation_id:op, template_id:item.id, nodes, connections};
    }

    function buildSmartWorkflow(templateId, options={}){
        const item = template(templateId);
        const selectedImage = workflowImage(item, options);
        const point = normalizePoint(options.point);
        const op = options.operation_id || operationId(item.id);
        const promptText = options.prompt || (item.id === 'image-to-video' ? 'Describe the motion and camera movement for this image.' : 'Describe the image you want to create.');
        const nodes = [];
        const connections = [];
        if(item.id === 'text-to-image'){
            nodes.push(smartPromptNode(`${op}_prompt`, {x:point.x, y:point.y}, promptText, '英文提示词'));
            nodes.push(smartImageNode(`${op}_image`, {x:point.x + 380, y:point.y}, [], 'Nano Banana', smartImageSettings()));
            connections.push(connection(`${op}_c_prompt_image`, `${op}_prompt`, `${op}_image`, 'input'));
        } else if(item.id === 'image-to-image'){
            nodes.push(selectedImage ? smartImageNode(`${op}_source`, {x:point.x, y:point.y}, [selectedImage], 'Selected Image') : emptySmartImageNode(`${op}_source`, {x:point.x, y:point.y}));
            nodes.push(smartPromptNode(`${op}_prompt`, {x:point.x + 360, y:point.y}, promptText, '英文提示词'));
            nodes.push(smartImageNode(`${op}_image`, {x:point.x + 740, y:point.y}, [], 'Nano Banana', smartImageSettings()));
            connections.push(connection(`${op}_c_source_image`, `${op}_source`, `${op}_image`, 'input'));
            connections.push(connection(`${op}_c_prompt_image`, `${op}_prompt`, `${op}_image`, 'input'));
        } else if(item.id === 'image-to-video'){
            nodes.push(selectedImage ? smartImageNode(`${op}_source`, {x:point.x, y:point.y}, [selectedImage], 'Selected Image') : emptySmartImageNode(`${op}_source`, {x:point.x, y:point.y}));
            nodes.push(smartPromptNode(`${op}_prompt`, {x:point.x + 360, y:point.y}, promptText, '英文运镜提示词'));
            nodes.push(smartImageNode(`${op}_video`, {x:point.x + 740, y:point.y}, [], 'Agnes Video', smartVideoSettings()));
            connections.push(connection(`${op}_c_source_video`, `${op}_source`, `${op}_video`, 'input'));
            connections.push(connection(`${op}_c_prompt_video`, `${op}_prompt`, `${op}_video`, 'input'));
        }
        return {format:'infinite-smart-canvas-workflow', operation_id:op, template_id:item.id, nodes, connections};
    }

    function buildEnglishPromptPreview(sourceText, mode='translate'){
        const clean = String(sourceText || '').trim();
        const safeMode = mode === 'optimize' ? 'optimize' : 'translate';
        const prefix = safeMode === 'optimize'
            ? 'Professional English prompt, preserve the original meaning and improve visual detail: '
            : 'English translation, preserve the original meaning: ';
        return {
            mode:safeMode,
            original_text:clean,
            english_text:clean ? `${prefix}${clean}` : '',
            action:'preview_or_create_english_prompt_node',
            overwrite_original:false,
            undoable:true,
        };
    }

    function markOperationProcessed(operation_id){
        if(!operation_id) return false;
        if(processedOperationIds.has(operation_id)) return false;
        processedOperationIds.add(operation_id);
        return true;
    }

    function workflowDragPayload(templateId){
        const item = template(templateId);
        return {
            kind:'builtin-workflow',
            templateId:item.id,
            name:item.name,
            provider_id:item.provider_id,
            model:item.model,
            requiresImage:item.requiresImage,
        };
    }

    window.CanvasWorkflowBuilder = {
        BUILTIN_WORKFLOW_TEMPLATES,
        IMAGE_PROVIDER,
        IMAGE_MODEL,
        IMAGE_PRO_MODEL,
        VIDEO_PROVIDER,
        VIDEO_MODEL,
        translationModes,
        templates:function(){ return BUILTIN_WORKFLOW_TEMPLATES.map(clone); },
        template,
        workflowDragPayload,
        buildClassicWorkflow,
        buildSmartWorkflow,
        buildEnglishPromptPreview,
        markOperationProcessed,
    };
})();
