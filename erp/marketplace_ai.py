import html
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProductContentError(Exception):
    pass


def _response_text(result):
    if result.get("output_text"):
        return result["output_text"]
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise ProductContentError("GPT 응답에서 상품 문구를 찾지 못했습니다.")


def generate_product_content(product):
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_PRODUCT_MODEL")
    if not api_key or not model:
        raise ProductContentError("OPENAI_API_KEY와 OPENAI_PRODUCT_MODEL 설정이 필요합니다.")
    material = "925 Silver" if product.pricing_material == "silver" else "14K/18K Gold"
    prompt = {
        "product_code": product.code, "current_name": product.name, "brand": product.brand,
        "category": product.category, "model_name": product.model_name, "material": material,
        "weight_g": str(product.default_weight or ""), "manufacturer": product.manufacturer,
        "origin_country": product.origin_country, "current_description": product.description,
        "seller_instruction": product.ai_instruction,
    }
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "naver_name": {"type": "string"}, "coupang_name": {"type": "string"},
            "summary": {"type": "string"},
            "sections": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                "required": ["title", "body"]}},
        }, "required": ["naver_name", "coupang_name", "summary", "sections"],
    }
    body = {
        "model": model,
        "instructions": "한국 주얼리 쇼핑몰의 상품 콘텐츠를 작성한다. 확인되지 않은 효능·인증·수치를 만들지 않는다. 상세페이지는 소재, 디자인, 사이즈, 착용, 관리, 포장, 배송/교환 안내 순서의 충분히 긴 섹션으로 작성한다.",
        "input": json.dumps(prompt, ensure_ascii=False),
        "text": {"format": {"type": "json_schema", "name": "jewelry_product_content", "strict": True, "schema": schema}},
        "max_output_tokens": 5000,
    }
    request = Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(), method="POST",
                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:800]
        raise ProductContentError(f"GPT API 오류 {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise ProductContentError(f"GPT API 연결 실패: {exc}") from exc
    content = json.loads(_response_text(result))
    sections = "".join(
        f'<section class="product-detail-section"><h2>{html.escape(row["title"])}</h2>'
        f'<p>{html.escape(row["body"]).replace(chr(10), "<br>")}</p></section>'
        for row in content["sections"]
    )
    content["detail_html"] = f'<div class="goldrium-product-detail">{sections}</div>'
    return content
