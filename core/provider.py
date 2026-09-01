from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


class NovelAIProvider:
    endpoint = "https://image.novelai.net/ai/generate-image"

    def __init__(self, token: str, config: dict, negative_prompt: str):
        if not token.startswith("pst-"):
            raise ValueError("NovelAI Persistent API 토큰(pst-…)이 필요합니다.")
        self.token = token
        self.config = config
        self.negative_prompt = negative_prompt

    def generate(self, prompt: str, seed: int, output_path: Path) -> Path:
        caption = {"caption": {"base_caption": prompt, "char_captions": []}, "use_coords": False, "use_order": True}
        negative = {"caption": {"base_caption": self.negative_prompt, "char_captions": []}, "legacy_uc": False}
        parameters = {
            "params_version": 3,
            "width": int(self.config.get("width", 832)),
            "height": int(self.config.get("height", 1216)),
            "seed": int(seed),
            "extra_noise_seed": int(seed),
            "n_samples": 1,
            "sampler": self.config.get("sampler", "k_euler_ancestral"),
            "steps": int(self.config.get("steps", 28)),
            "scale": float(self.config.get("scale", 7.0)),
            "cfg_rescale": float(self.config.get("cfg_rescale", 0.6)),
            "noise_schedule": self.config.get("noise_schedule", "karras"),
            "negative_prompt": self.negative_prompt,
            "qualityToggle": False,
            "ucPreset": 0,
            "image_format": "png",
            "v4_prompt": caption,
            "v4_negative_prompt": negative,
        }
        if self.config.get("variety_plus", False):
            parameters["skip_cfg_above_sigma"] = 58

        body = json.dumps({
            "action": "generate",
            "input": prompt,
            "model": self.config["model"],
            "parameters": parameters,
        }).encode()
        request = urllib.request.Request(
            self.endpoint,
            body,
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/zip",
                "User-Agent": "ArtistWeightBO/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                content = response.read()
        except urllib.error.HTTPError as error:
            try:
                detail = error.read(600).decode("utf-8", "replace")
            except Exception:
                detail = ""
            if error.code == 401:
                raise RuntimeError("NovelAI 인증 실패 (401): 토큰을 확인하세요.") from error
            if error.code == 402:
                raise RuntimeError("NovelAI Anlas 부족 또는 구독 필요 (402).") from error
            if error.code == 429:
                raise RuntimeError("NovelAI 요청 제한 (429): 잠시 후 다시 시도하세요.") from error
            raise RuntimeError(f"NovelAI 서버 오류 (HTTP {error.code}): {detail}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"NovelAI 서버 연결 실패: {error.reason}") from error

        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = [n for n in archive.namelist() if n.lower().endswith((".png", ".webp", ".jpg", ".jpeg"))]
                if not names:
                    raise RuntimeError("NovelAI 응답 압축 파일에 이미지가 없습니다.")
                image_bytes = archive.read(names[0])
        except zipfile.BadZipFile:
            result = json.loads(content)
            images = result.get("images") or []
            image_bytes = base64.b64decode(images[0]["image"])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return output_path


class MockProvider:
    """No API token needed — deterministic placeholder image for UI testing."""

    def generate(self, prompt: str, seed: int, output_path: Path) -> Path:
        from PIL import Image, ImageDraw

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (512, 768), (30 + seed % 200, 60, 90))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), prompt[:400], fill=(255, 255, 255))
        img.save(output_path)
        return output_path
