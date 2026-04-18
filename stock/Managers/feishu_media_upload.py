"""
飞书开放平台：tenant_access_token 与上传图片（im/v1/images），用于 Webhook/OAPI 发图。
需应用开启机器人能力并拥有上传图片相关权限。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


def feishu_obtain_tenant_access_token(
    app_id: str,
    app_secret: str,
    *,
    timeout: float = 15.0,
) -> Optional[str]:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    aid = (app_id or "").strip()
    sec = (app_secret or "").strip()
    if not aid or not sec:
        logger.error("飞书获取 tenant_access_token 失败：app_id/app_secret 为空（请在群组管理的飞书 group 配置中填写）")
        return None
    try:
        resp = requests.post(
            url,
            json={"app_id": aid, "app_secret": sec},
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        logger.error("飞书获取 tenant_access_token 请求异常: %s", e)
        return None
    try:
        data: Dict[str, Any] = resp.json()
    except ValueError:
        logger.error("飞书 tenant_token 响应非 JSON: %s", (resp.text or "")[:300])
        return None
    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error("飞书 tenant_token HTTP %s: %s", resp.status_code, str(data)[:500])
        return None
    raw_code = data.get("code")
    raw_msg = data.get("msg")
    try:
        code_int = int(raw_code if raw_code is not None and raw_code != "" else -1)
    except Exception:
        code_int = -999999

    # 版本标记：用于确认线上运行的是否为当前逻辑
    logger.info(
        "feishu_tenant_token_check[v2]: http=%s raw_code=%r code_int=%s msg=%r has_token=%s",
        resp.status_code,
        raw_code,
        code_int,
        raw_msg,
        bool(data.get("tenant_access_token")),
    )

    if code_int != 0:
        code = raw_code
        msg = raw_msg
        logger.error(
            "飞书 tenant_token 业务错误 code=%s msg=%s raw=%s",
            code,
            msg,
            str(data)[:500],
        )
        logger.error(
            "提示：本实现使用 /auth/v3/tenant_access_token/internal，仅适用于「自建应用(企业自用)」app_id/app_secret；"
            "若你用的是其他类型应用/凭证不匹配，会导致获取 token 失败。"
        )
        return None
    tok = data.get("tenant_access_token")
    if not tok:
        logger.error("飞书 tenant_token 获取成功但 tenant_access_token 为空 raw=%s", str(data)[:500])
    return str(tok).strip() if tok else None


def feishu_upload_im_image(
    tenant_access_token: str,
    image_bytes: bytes,
    *,
    filename: str = "notify_card.png",
    timeout: float = 45.0,
) -> Optional[str]:
    """
    上传图片，image_type=message，返回 image_key。
    """
    tok = (tenant_access_token or "").strip()
    if not tok:
        return None
    if not image_bytes:
        logger.error("飞书上传图片：数据为空")
        return None
    url = "https://open.feishu.cn/open-apis/im/v1/images"
    headers = {"Authorization": f"Bearer {tok}"}
    files = {"image": (filename or "card.png", image_bytes, "image/png")}
    data = {"image_type": "message"}
    try:
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=timeout)
    except requests.RequestException as e:
        logger.error("飞书上传图片请求异常: %s", e)
        return None
    try:
        body: Dict[str, Any] = resp.json()
    except ValueError:
        logger.error("飞书上传图片响应非 JSON: %s", (resp.text or "")[:300])
        return None

    raw_code = body.get("code")
    raw_msg = body.get("msg")
    try:
        code_int = int(raw_code if raw_code is not None and raw_code != "" else -1)
    except Exception:
        code_int = -999999

    # 版本标记：用于确认线上运行的是否为当前逻辑
    logger.info(
        "feishu_upload_check[v2]: http=%s raw_code=%r code_int=%s msg=%r has_image_key=%s",
        resp.status_code,
        raw_code,
        code_int,
        raw_msg,
        bool((body.get("data") or {}).get("image_key")),
    )

    if code_int != 0:
        logger.error("飞书上传图片失败: %s", str(body)[:500])
        return None
    d = body.get("data") or {}
    key = d.get("image_key")
    if not key:
        logger.error("飞书上传图片返回成功但 image_key 为空: %s", str(body)[:500])
    return str(key).strip() if key else None
