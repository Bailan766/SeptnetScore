# -*- coding: utf-8 -*-
"""
七天学堂 (7net) 登录、查分与排名看板 Web 服务端
启动方式:
    python app.py
默认监听:
    http://127.0.0.1:8765
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

from api_client import DemoSeptnetClient, SeptnetClient, UserSession

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "session.json")

# 全局客户端实例（单机桌面/本地 Web 使用）
LIVE_CLIENT = SeptnetClient()
DEMO_CLIENT = DemoSeptnetClient()
CURRENT_MODE = "live" if LIVE_CLIENT.load_session(SESSION_FILE) else "demo"


class ScoreAppHandler(BaseHTTPRequestHandler):
    """处理前端页面静态资源与本地 API 代理请求"""

    def _send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return json.loads(raw) if raw else {}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = dict(urllib.parse.parse_qsl(parsed.query))

        if path in ("/", "/index.html"):
            index_path = os.path.join(BASE_DIR, "index.html")
            with open(index_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/api/state":
            if CURRENT_MODE == "demo" or not LIVE_CLIENT.session.token:
                exams = DEMO_CLIENT.get_exams()
                bundle = DEMO_CLIENT.get_full_exam_bundle(exams[0]["examGuid"])
                self._send_json(
                    {
                        "ok": True,
                        "mode": "demo",
                        "exams": exams,
                        "bundle": bundle,
                    }
                )
            else:
                exams = LIVE_CLIENT.get_live_exams()
                bundle = LIVE_CLIENT.get_live_exam_bundle("", exams)
                self._send_json(
                    {
                        "ok": True,
                        "mode": "live",
                        "token": LIVE_CLIENT.session.token,
                        "exams": exams,
                        "bundle": bundle,
                    }
                )
            return

        if path == "/api/demo/bundle":
            exam_guid = query.get("examGuid", "")
            exams = DEMO_CLIENT.get_exams()
            bundle = DEMO_CLIENT.get_full_exam_bundle(exam_guid or exams[0]["examGuid"])
            self._send_json({"ok": True, "mode": "demo", "exams": exams, "bundle": bundle})
            return

        if path == "/api/live/bundle":
            exam_guid = query.get("examGuid", "")
            exams = LIVE_CLIENT.get_live_exams()
            bundle = LIVE_CLIENT.get_live_exam_bundle(exam_guid, exams)
            self._send_json(
                {
                    "ok": True,
                    "mode": "live",
                    "token": LIVE_CLIENT.session.token,
                    "exams": exams,
                    "bundle": bundle,
                }
            )
            return

        if path == "/api/sms/captcha":
            user_code = query.get("userCode", "13800138000")
            img_url = SeptnetClient.get_verify_image_url(user_code=user_code)
            try:
                req = urllib.request.Request(
                    img_url,
                    headers={"User-Agent": "Mozilla/5.0 SeptnetStudent/4.6.4"},
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    img_bytes = resp.read()
                    ctype = resp.headers.get("Content-Type", "image/png")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(img_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(img_bytes)
            except Exception:
                # 网关不可达或离线时返回本地 SVG 占位图形验证码
                svg = (
                    '<svg xmlns="http://www.w3.org/2000/svg" width="110" height="36">'
                    '<rect width="100%" height="100%" rx="6" fill="#0b1120" stroke="#334155"/>'
                    '<text x="50%" y="56%" dominant-baseline="middle" text-anchor="middle" '
                    'fill="#38bdf8" font-family="monospace" font-size="16" font-weight="bold">7N46</text>'
                    "</svg>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
                self.send_header("Content-Length", str(len(svg)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(svg)
            return

        self._send_json({"ok": False, "message": f"Not Found: {path}"}, status=404)

    def do_POST(self) -> None:
        global CURRENT_MODE
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()

            if path == "/api/mode":
                mode = body.get("mode", "demo")
                CURRENT_MODE = "live" if mode == "live" else "demo"
                self._send_json({"ok": True, "mode": CURRENT_MODE})
                return

            if path == "/api/sms/send":
                user_code = str(body.get("userCode", "")).strip()
                graphic_code = str(body.get("graphicCode", "")).strip() or None
                api_path = str(body.get("apiPath", "login/sendsms")).strip()

                if not user_code or len(user_code) < 11:
                    self._send_json(
                        {"ok": False, "message": "请输入 11 位手机号码 (userCode)"},
                        status=400,
                    )
                    return

                try:
                    res = LIVE_CLIENT.send_sms(
                        user_code=user_code,
                        verification_code=graphic_code,
                        api_path=api_path,
                    )
                    token_val = (
                        res.get("token", "")
                        if isinstance(res, dict)
                        else str(res or "")
                    )
                    self._send_json(
                        {
                            "ok": True,
                            "smsToken": token_val,
                            "apiPath": "login/SendSMSV3" if graphic_code else api_path,
                            "message": "短信验证码已通过网关发送，请注意查收",
                        }
                    )
                except Exception as sms_exc:
                    self._send_json(
                        {
                            "ok": False,
                            "message": f"网关发送返回: {sms_exc}",
                        },
                        status=400,
                    )
                return

            if path == "/api/login":
                login_type = body.get("loginType", "password")
                if login_type == "demo":
                    CURRENT_MODE = "demo"
                    exams = DEMO_CLIENT.get_exams()
                    bundle = DEMO_CLIENT.get_full_exam_bundle(exams[0]["examGuid"])
                    self._send_json(
                        {
                            "ok": True,
                            "mode": "demo",
                            "exams": exams,
                            "bundle": bundle,
                        }
                    )
                    return

                CURRENT_MODE = "live"
                if login_type == "token":
                    LIVE_CLIENT.session = UserSession(
                        token=str(body.get("token", "")).strip(),
                        user_code=str(body.get("userCode", "")).strip(),
                        student_name=str(body.get("studentName", "")).strip(),
                        school_guid=str(body.get("schoolGuid", "")).strip(),
                        current_grade=str(body.get("grade", "")).strip(),
                        ru_code=str(body.get("ruCode", "")).strip(),
                    )
                    try:
                        LIVE_CLIENT.get_user_info()
                    except Exception:
                        pass
                else:
                    user_code = str(body.get("userCode", "")).strip()
                    password = str(body.get("password", "")).strip()
                    verify_code = str(body.get("verifyCode", "")).strip() or None
                    sms_token = str(body.get("smsToken", "")).strip() or None
                    pwd_encoded = (
                        SeptnetClient.encode_credential_field(password)
                        if password
                        else ""
                    )
                    LIVE_CLIENT.login(
                        user_code=user_code,
                        password_encoded=pwd_encoded,
                        verify_code=verify_code,
                        sms_token=sms_token,
                    )
                    try:
                        LIVE_CLIENT.get_user_info()
                    except Exception:
                        pass

                LIVE_CLIENT.save_session(SESSION_FILE)
                exam_list = LIVE_CLIENT.get_live_exams()
                bundle = LIVE_CLIENT.get_live_exam_bundle("", exam_list)
                self._send_json(
                    {
                        "ok": True,
                        "mode": "live",
                        "token": LIVE_CLIENT.session.token,
                        "user": {
                            "studentName": LIVE_CLIENT.session.student_name,
                            "schoolName": LIVE_CLIENT.session.school_name,
                            "currentGrade": LIVE_CLIENT.session.current_grade,
                            "userCode": LIVE_CLIENT.session.user_code,
                            "isVip": LIVE_CLIENT.session.is_vip,
                        },
                        "exams": exam_list,
                        "bundle": bundle,
                    }
                )
                return

            if path == "/api/live/query":
                action = body.get("action", "scoreReport")
                exam_guid = str(body.get("examGuid", ""))
                km = str(body.get("km", "总分"))
                rule_hash = str(body.get("ruleHash", ""))
                sort_desc = str(body.get("sortDesc", ""))
                scope = int(body.get("scope", 2))

                if action == "scoreReport":
                    data = LIVE_CLIENT.query_score_report(exam_guid=exam_guid, km=km)
                elif action == "position":
                    data = LIVE_CLIENT.query_grade_position(
                        exam_guid=exam_guid,
                        km=km,
                        rule_hash=rule_hash,
                        sort_desc=sort_desc,
                        scope=scope,
                    )
                elif action == "topAvg":
                    data = LIVE_CLIENT.query_top_avg_compare(exam_guid=exam_guid)
                elif action == "thAnswers":
                    data = LIVE_CLIENT.query_th_answers(
                        exam_guid=exam_guid,
                        km=km,
                        rule_hash=rule_hash,
                    )
                elif action == "trends":
                    data = LIVE_CLIENT.query_performance_trends(
                        exam_guid=exam_guid,
                        km=km,
                        rule_hash=rule_hash,
                    )
                else:
                    data = LIVE_CLIENT.get_exam_report_info(exam_guid=exam_guid)

                self._send_json({"ok": True, "data": data})
                return

            self._send_json({"ok": False, "message": f"Unknown endpoint: {path}"}, status=404)

        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=400)


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = HTTPServer((host, port), ScoreAppHandler)
    print(f"[7net Score & Ranking App] Running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()


if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    run_server(port=port_arg)
