"""ScholarNoteLM adapter: explicit local checkpoints; no network or mock fallback."""
import os
from pathlib import Path
from surya.detection import DetectionPredictor, InlineDetectionPredictor
from surya.layout import LayoutPredictor
from surya.ocr_error import OCRErrorPredictor
from surya.recognition import RecognitionPredictor
from surya.table_rec import TableRecPredictor
from surya.texify import TexifyPredictor

def create_model_dict(device=None,dtype=None):
    root=Path(os.environ['SCHOLARNOTELM_ROOT'])/'models/marker'
    specs=[('layout_model',LayoutPredictor,'layout/2025_02_18'),('texify_model',TexifyPredictor,'texify/2025_02_18'),('recognition_model',RecognitionPredictor,'text_recognition/2025_02_18'),('table_rec_model',TableRecPredictor,'table_recognition/2025_02_18'),('detection_model',DetectionPredictor,'text_detection/2025_02_28'),('inline_detection_model',InlineDetectionPredictor,'inline_math_detection/2025_02_24'),('ocr_error_model',OCRErrorPredictor,'ocr_error_detection/2025_02_18')]
    models={}
    for key,cls,path in specs:
        checkpoint=root/path
        if not (checkpoint/'config.json').is_file():raise RuntimeError('缺少本地 Marker 模型：'+str(checkpoint))
        print('加载本地模型：'+key,flush=True)
        models[key]=cls(device=device,dtype=dtype,checkpoint=str(checkpoint))
    return models
