# app/products/service.py
import os
from .parsers.item_parser import extract_features_from_url

class ProductService:
    def __init__(self, model_dir: str = None):
        self.model_dir = model_dir

    async def parse_product_link(self, url: str):
        # 원본의 정교한 파싱 로직(item_parser.py)을 그대로 사용합니다.
        result = extract_features_from_url(url, model_dir=self.model_dir)
        
        # 7-블록 JSON 형식을 위해 필드명 보정 (product_name -> name)
        if "product_name" in result:
            result["name"] = result.get("product_name")
            
        return result
