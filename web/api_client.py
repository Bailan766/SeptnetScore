# -*- coding: utf-8 -*-
"""
七天学堂 (cc.septnet.student v4.6.4) API 客户端与数据模型
完整还原 Android 客户端底层网络层与原生加解密体系：
1. 本地 AES-256-GCM 动态密钥协商 (LocalAesCryptoUtil / septnetlive)
2. 保持小写 bk / bn / bp 特殊请求头与 Android User-Agent
3. 考试列表拉取与静态 AES-256-ECB 解密
4. 解锁普通非VIP账号的年级排名与百分位折算 (Question/Subjects -> studentCount & sortDesc)
5. 各科赋分与原始分对照、AI综合学情诊断、小题全校作答选项分布
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import unpad


class SeptnetDomains:
    """微服务网关地址"""

    INDEX = "https://szone-index.7net.cc/"
    USER = "https://szone-my.7net.cc/"
    SCORE = "https://szone-score.7net.cc/"
    HOMEWORK = "https://szone-homework.7net.cc/"
    DEEPSTUDY = "https://szone-deepstudy.7net.cc/"
    ACTIVITY = "https://szone-activity.7net.cc/"
    VERSION = "4.6.4"
    STATIC_AES_KEY = b"c0f1a30cba2147949ee71cf71cba3c20"
    RSA_PUB_B64 = (
        "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDrjEcFVWu6mizSyP3fCCaWZ3BeTeuZx44H"
        "HcWhzq6+FkueApOJbifi0VfaUO6S9eHvaJSEaCUFouD3cxr3fOk8RYQw1S1BcTscEbnqq/PC"
        "uoj5vj12t/M3dbqTdNKCrufSukwBask+OOHenu9IJzkmvrPurLnIC3yDTy3Ix9YliQIDAQAB"
    )
    USER_AGENT = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 SeptnetStudent/4.6.4"


@dataclass
class UserSession:
    """登录会话与绑定的学生信息"""

    token: str = ""
    user_code: str = ""
    user_guid: str = ""
    student_name: str = ""
    school_guid: str = ""
    school_name: str = ""
    ru_code: str = ""
    current_grade: str = ""
    school_grade: str = ""
    is_vip: bool = False
    raw_aes_key_b64: str = ""
    bk: str = ""
    raw_info: Dict[str, Any] = field(default_factory=dict)


class SeptnetClient:
    """
    七天学堂 REST API 客户端
    封装原生加解密、登录、考试列表、成绩单、排名折算与小题明细接口。
    """

    def __init__(
        self,
        session: Optional[UserSession] = None,
        timeout: int = 12,
    ) -> None:
        self.session = session or UserSession()
        self.timeout = timeout
        self.raw_aes_key: Optional[bytes] = None
        if self.session.raw_aes_key_b64:
            try:
                self.raw_aes_key = base64.b64decode(self.session.raw_aes_key_b64)
            except Exception:
                self.raw_aes_key = None

    @staticmethod
    def encode_credential_field(
        value: str, suffix: str = "{MTgyMjU2MDU0MjF7c3pvbmV9}"
    ) -> str:
        """
        对应前端 e/ey 模块的字段编码器:
        btoa(value + "{MTgyMjU2MDU0MjF7c3pvbmV9}")
        """
        if not value:
            return value
        raw = f"{value}{suffix}".encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def init_aes_key(self) -> None:
        """
        生成 32 字节本地 AES-256 随机密钥，并使用 RSA 公钥加密生成请求头 bk
        """
        self.raw_aes_key = os.urandom(32)
        self.session.raw_aes_key_b64 = base64.b64encode(self.raw_aes_key).decode("ascii")
        rsa_key = RSA.import_key(base64.b64decode(SeptnetDomains.RSA_PUB_B64))
        rsa_cipher = PKCS1_v1_5.new(rsa_key)
        self.session.bk = base64.b64encode(
            rsa_cipher.encrypt(self.session.raw_aes_key_b64.encode("utf-8"))
        ).decode("ascii")

    def aes_key_exchange(self) -> bool:
        """
        将加密后的 AES 密钥登记至网关微服务
        POST https://szone-my.7net.cc/user
        """
        if not self.raw_aes_key or not self.session.bk:
            self.init_aes_key()

        conn = http.client.HTTPSConnection("szone-my.7net.cc", timeout=self.timeout)
        headers = {
            "Version": SeptnetDomains.VERSION,
            "User-Agent": SeptnetDomains.USER_AGENT,
            "check-webp": "false",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "bk": self.session.bk,
        }
        if self.session.token:
            headers["Token"] = self.session.token

        conn.request("POST", "/user", body=b"", headers=headers)
        resp = conn.getresponse()
        resp_body = resp.read().decode("utf-8", errors="replace")
        conn.close()
        try:
            res_json = json.loads(resp_body)
            return res_json.get("status") == 200
        except Exception:
            return False

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        is_encrypt: bool = False,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        底层网络请求封装，使用 http.client.HTTPSConnection 确保 headers 键名完全保持小写
        (避免 urllib.request 将 bk/bn/bp 首字母自动大写导致 7net 服务端拒绝识别)
        """
        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        parsed_url = urllib.parse.urlparse(url)
        host = parsed_url.netloc
        path = parsed_url.path or "/"

        headers: Dict[str, str] = {
            "Version": SeptnetDomains.VERSION,
            "User-Agent": SeptnetDomains.USER_AGENT,
            "check-webp": "false",
        }
        if self.session.token:
            headers["Token"] = self.session.token
        if extra_headers:
            headers.update(extra_headers)

        body_bytes: bytes = b""

        if is_encrypt:
            if not self.raw_aes_key or not self.session.bk:
                self.init_aes_key()
                self.aes_key_exchange()

            headers["bk"] = self.session.bk
            if params:
                # 键值对以分号拼接后使用 AES-256-GCM 加密为 bp 和 bn
                plaintext = ";".join(f"{k}={v}" for k, v in params.items()).encode("utf-8")
                iv = os.urandom(12)
                cipher = AES.new(self.raw_aes_key, AES.MODE_GCM, nonce=iv, mac_len=16)
                ct, tag = cipher.encrypt_and_digest(plaintext)
                headers["bn"] = base64.b64encode(iv).decode("ascii")
                headers["bp"] = base64.b64encode(ct + tag).decode("ascii")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
        else:
            if method.upper() == "GET":
                if params:
                    qs = urllib.parse.urlencode(params)
                    path = f"{path}?{qs}"
                headers["Content-Type"] = "application/json; charset=utf-8"
            else:
                body_bytes = urllib.parse.urlencode(params).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"

        conn = http.client.HTTPSConnection(host, timeout=self.timeout)
        conn.request(method.upper(), path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        raw_text = resp.read().decode("utf-8", errors="replace")
        conn.close()

        payload = json.loads(raw_text) if raw_text else {}
        return self._extract_response(payload, is_encrypt=is_encrypt)

    def _extract_response(self, payload: Dict[str, Any], is_encrypt: bool = False) -> Any:
        """解密并提取业务数据"""
        if not isinstance(payload, dict):
            return payload

        data = payload.get("data")
        # 1. 动态 AES-256-GCM 解密
        if isinstance(data, dict) and data.get("bn") and data.get("content") and self.raw_aes_key:
            try:
                iv = base64.b64decode(data["bn"])
                raw_ct = base64.b64decode(data["content"])
                pt = AES.new(self.raw_aes_key, AES.MODE_GCM, nonce=iv).decrypt_and_verify(
                    raw_ct[:-16], raw_ct[-16:]
                ).decode("utf-8")
                data = json.loads(pt)
                payload["data"] = data
            except Exception:
                pass

        # 2. 静态 AES-256-ECB 解密 (例如 getClaimExams)
        if isinstance(data, dict) and data.get("isEncrypt") and data.get("content"):
            try:
                raw_ct = base64.b64decode(str(data["content"]))
                cipher = AES.new(SeptnetDomains.STATIC_AES_KEY, AES.MODE_ECB)
                pt = unpad(cipher.decrypt(raw_ct), AES.block_size).decode("utf-8")
                data = json.loads(pt)
                payload["data"] = data
            except Exception:
                pass

        status = payload.get("status", 200)
        if status == 200:
            return payload.get("data", payload)
        raise RuntimeError(f"API Error (status={status}): {payload.get('message', '未知错误')}")

    # =========================================================================
    # 1. 登录与用户信息接口 (https://szone-my.7net.cc/)
    # =========================================================================

    @staticmethod
    def get_verify_image_url(user_code: str, timestamp: Optional[int] = None) -> str:
        """获取图形验证码图片地址"""
        import time

        ts = timestamp or int(time.time() * 1000)
        q = urllib.parse.urlencode({"userCode": user_code, "timestamp": ts})
        return f"{SeptnetDomains.USER}VerifyImage?{q}"

    def login(
        self,
        user_code: str,
        password_encoded: str = "",
        verify_code: Optional[str] = None,
        sms_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        账号密码或短信验证码登录
        """
        endpoint = "login/entry" if verify_code else "login"
        body: Dict[str, Any] = {
            "userCode": user_code,
            "password": password_encoded,
        }
        if verify_code:
            body["verifyCode"] = verify_code
        if sms_token:
            body["token"] = sms_token

        res = self._request("POST", SeptnetDomains.USER + endpoint, body)
        if isinstance(res, dict) and res.get("token"):
            self.session.token = res["token"]
            self.session.user_code = user_code
        elif isinstance(res, str) and res:
            self.session.token = res
            self.session.user_code = user_code

        # 登录成功后立即初始化本地 AES-256 密钥并完成协商
        self.init_aes_key()
        self.aes_key_exchange()

        return res if isinstance(res, dict) else {"token": res}

    def get_user_info(self) -> UserSession:
        """
        获取当前登录用户及绑定学生档案
        - GET https://szone-my.7net.cc/userInfo/GetUserInfo
        """
        if not self.session.bk:
            self.init_aes_key()
            self.aes_key_exchange()

        res = self._request(
            "GET",
            SeptnetDomains.USER + "userInfo/GetUserInfo",
            {},
            is_encrypt=True,
        )
        if isinstance(res, dict):
            self.session.user_guid = str(res.get("userGuid", ""))
            self.session.user_code = str(res.get("userCode", self.session.user_code))
            self.session.student_name = str(res.get("studentName", ""))
            self.session.school_guid = str(res.get("schoolGuid", ""))
            self.session.school_name = str(res.get("schoolName", ""))
            self.session.ru_code = str(res.get("ruCode", ""))
            grade_raw = str(res.get("currentGrade") or res.get("grade") or "G2")
            self.session.current_grade = grade_raw.upper()
            self.session.school_grade = str(res.get("schoolGrade", ""))
            self.session.is_vip = bool(res.get("isVip", False))
            self.session.raw_info = res
        return self.session

    # =========================================================================
    # 2. 考试列表与学科成绩单接口 (https://szone-score.7net.cc/)
    # =========================================================================

    def get_claim_exams(self, start_index: int = 0, rows: int = 20) -> Dict[str, Any]:
        """获取已认领考试列表"""
        return self._request(
            "GET",
            SeptnetDomains.SCORE + "exam/getClaimExams",
            {
                "startIndex": start_index,
                "rows": rows,
                "schoolGuid": self.session.school_guid,
                "grade": self.session.current_grade,
            },
        )

    def query_exam_subjects(self, exam_guid: str) -> Dict[str, Any]:
        """POST Question/Subjects - 获取考试科目列表及考生人数与排名百分位"""
        return self._request(
            "POST",
            SeptnetDomains.SCORE + "Question/Subjects",
            {
                "examGuid": exam_guid,
                "schoolGuid": self.session.school_guid,
                "grade": self.session.current_grade,
                "schoolRuCode": self.session.ru_code,
            },
            is_encrypt=True,
        )

    def query_score_report(self, exam_guid: str, km: str = "总分") -> Dict[str, Any]:
        """POST Question/ScoreReport - 获取总分与单科成绩单"""
        return self._request(
            "POST",
            SeptnetDomains.SCORE + "Question/ScoreReport",
            {
                "examGuid": exam_guid,
                "schoolGuid": self.session.school_guid,
                "grade": self.session.current_grade,
                "schoolRuCode": self.session.ru_code,
                "km": km,
            },
            is_encrypt=True,
        )

    def query_subject_th_distri(
        self, exam_guid: str, km: str, response_guid: str = ""
    ) -> List[Dict[str, Any]]:
        """POST Question/SubjectTHDistri - 获取单科各题全校选项分布"""
        res = self._request(
            "POST",
            SeptnetDomains.SCORE + "Question/SubjectTHDistri",
            {
                "examGuid": exam_guid,
                "schoolGuid": self.session.school_guid,
                "grade": self.session.current_grade,
                "schoolRuCode": self.session.ru_code,
                "km": km,
                "srcKm": km,
                "responseGuid": response_guid,
            },
            is_encrypt=True,
        )
        return res if isinstance(res, list) else []

    # =========================================================================
    # 3. 会话持久化与数据打包渲染
    # =========================================================================

    def save_session(self, path: str) -> None:
        data = {
            "token": self.session.token,
            "user_code": self.session.user_code,
            "user_guid": self.session.user_guid,
            "student_name": self.session.student_name,
            "school_guid": self.session.school_guid,
            "school_name": self.session.school_name,
            "ru_code": self.session.ru_code,
            "current_grade": self.session.current_grade,
            "school_grade": self.session.school_grade,
            "is_vip": self.session.is_vip,
            "raw_aes_key_b64": self.session.raw_aes_key_b64,
            "bk": self.session.bk,
            "raw_info": self.session.raw_info,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_session(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if not d.get("token"):
                return False
            self.session = UserSession(
                token=str(d.get("token", "")),
                user_code=str(d.get("user_code", "")),
                user_guid=str(d.get("user_guid", "")),
                student_name=str(d.get("student_name", "")),
                school_guid=str(d.get("school_guid", "")),
                school_name=str(d.get("school_name", "")),
                ru_code=str(d.get("ru_code", "")),
                current_grade=str(d.get("current_grade", "G2")),
                school_grade=str(d.get("school_grade", "")),
                is_vip=bool(d.get("is_vip", False)),
                raw_aes_key_b64=str(d.get("raw_aes_key_b64", "")),
                bk=str(d.get("bk", "")),
                raw_info=d.get("raw_info") or {},
            )
            if self.session.raw_aes_key_b64:
                self.raw_aes_key = base64.b64decode(self.session.raw_aes_key_b64)
            return True
        except Exception:
            return False

    def get_live_exams(self) -> List[Dict[str, Any]]:
        """拉取当前账号已认领的全部真实考试"""
        exams: List[Dict[str, Any]] = []
        try:
            res = self.get_claim_exams(0, 25)
            items = (
                res.get("list", [])
                if isinstance(res, dict)
                else (res if isinstance(res, list) else [])
            )
            for item in items:
                if not isinstance(item, dict):
                    continue
                eg = str(item.get("examGuid") or item.get("guid") or "")
                if not eg:
                    continue
                exams.append(
                    {
                        "examGuid": eg,
                        "examName": str(item.get("examName") or "未命名考试"),
                        "examType": str(item.get("examType") or ("联考" if item.get("isUnion") else "统考")),
                        "queryTime": str(
                            item.get("queryTime")
                            or item.get("examTime")
                            or item.get("publishTime")
                            or "-"
                        ),
                        "ruleHash": str(item.get("ruleHash") or ""),
                        "isUnion": bool(item.get("isUnion", False)),
                        "totalScore": item.get("score") or item.get("totalScore") or "-",
                        "fullScore": item.get("fullScore") or 750,
                        "raw": item,
                    }
                )
        except Exception:
            pass
        return exams

    def get_live_exam_bundle(
        self,
        exam_guid: str = "",
        exams: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        拉取单场真实考试的成绩单、赋分转换、解锁非VIP年级排名及小题分布
        """
        if exams is None:
            exams = self.get_live_exams()

        user_dict = {
            "studentName": self.session.student_name or "已登录用户",
            "schoolName": self.session.school_name or "-",
            "currentGrade": self.session.current_grade or "高二",
            "userCode": self.session.user_code or "-",
            "isVip": self.session.is_vip,
        }

        if not exams:
            return {
                "exam": {
                    "examGuid": "",
                    "examName": "当前账号暂无已认领考试记录",
                    "examType": "实连状态",
                    "queryTime": "-",
                    "ruleHash": "",
                    "isUnion": False,
                    "totalScore": "-",
                    "fullScore": "-",
                },
                "user": user_dict,
                "subjects": [],
                "positionBuckets": [],
                "trends": [],
            }

        target_exam = next((e for e in exams if e["examGuid"] == exam_guid), exams[0])
        eg = target_exam["examGuid"]

        # 1. 查询 Question/Subjects
        sub_map: Dict[str, Any] = {}
        student_count = 0
        ai_conclusion = ""
        try:
            sub_res = self.query_exam_subjects(exam_guid=eg)
            if isinstance(sub_res, dict):
                student_count = int(sub_res.get("exam_info", {}).get("studentCount") or 0)
                for item in sub_res.get("list", []):
                    km = item.get("km")
                    if km:
                        sub_map[km] = item
                        if km == "总分" and item.get("summary", {}).get("conclusion"):
                            ai_conclusion = item["summary"]["conclusion"]
        except Exception:
            pass

        # 2. 查询 Question/ScoreReport
        sr_km_list: List[Dict[str, Any]] = []
        try:
            sr_res = self.query_score_report(exam_guid=eg, km="总分")
            if isinstance(sr_res, dict):
                sr_km_list = sr_res.get("km_list") or []
        except Exception:
            pass

        # 3. 组装 subjects 列表并解锁年级排名
        subjects: List[Dict[str, Any]] = []

        # 优先以 ScoreReport 的 km_list 为准，再补充 Subjects 的百分位与考生总数
        ordered_kms = ["总分", "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]
        sr_dict = {k.get("km"): k for k in sr_km_list if isinstance(k, dict) and k.get("km")}

        for km_name in ordered_kms:
            sr_item = sr_dict.get(km_name)
            sub_item = sub_map.get(km_name)
            if not sr_item and not sub_item:
                continue

            # 过滤缺考科目
            if sr_item and (str(sr_item.get("score")) == "缺考" or sr_item.get("kmTag") == -100):
                continue
            if sub_item and sub_item.get("code") == -1:
                continue

            si = (sub_item or {}).get("scoreInfo", {})
            sort_desc = si.get("sortDesc", "")
            percentile: Optional[float] = None
            if sort_desc and "," in sort_desc:
                try:
                    p_val = sort_desc.split(",")[0]
                    if p_val != "-":
                        percentile = float(p_val)
                except Exception:
                    percentile = None

            calc_grade_rank = "-"
            if percentile is not None and student_count > 0:
                calc_grade_rank = str(round(student_count * percentile / 100))

            is_fu = bool(sr_item.get("isFu") if sr_item else False)
            raw_score = sr_item.get("score") if sr_item else target_exam.get("totalScore", "-")
            fu_score = sr_item.get("fuScore") if sr_item else raw_score
            display_score = fu_score if is_fu and fu_score and fu_score != "0" else raw_score

            full_score = sr_item.get("fullScore") if sr_item else target_exam.get("fullScore", 150)
            rating_level = (sr_item.get("grade") if sr_item else None) or si.get("grade") or "-"

            # 查询首个选中学科（如语文）的小题选项分布
            ths = []
            if km_name not in ("总分", "全科") and sub_item and sub_item.get("responseGuid"):
                try:
                    distri_data = self.query_subject_th_distri(
                        exam_guid=eg,
                        km=km_name,
                        response_guid=sub_item.get("responseGuid", ""),
                    )
                    for d in distri_data[:25]:
                        th_no = str(d.get("th", ""))
                        dist_list = d.get("distri", [])
                        top_choice = dist_list[0] if dist_list else {}
                        ths.append({
                            "th": th_no,
                            "type": "单项选择" if len(dist_list) >= 4 else "题目",
                            "myScore": "-",
                            "fullScore": "-",
                            "myAns": "见答卷",
                            "stdAns": f"全校首选 {top_choice.get('key', '')} ({top_choice.get('value', '')}%)",
                            "rate": f"{top_choice.get('value', '')}%",
                        })
                except Exception:
                    pass

            subjects.append({
                "km": km_name,
                "isAll": km_name == "总分",
                "myScore": display_score,
                "rawScore": raw_score,
                "isFu": is_fu,
                "fullScore": full_score,
                "kgScore": "-",
                "zgScore": "-",
                "classRank": "-",
                "classTotal": "-",
                "gradeRank": calc_grade_rank,
                "gradeTotal": str(student_count) if student_count else "-",
                "unionRank": None,
                "unionTotal": None,
                "level": rating_level,
                "sortDesc": f"前 {percentile}%" if percentile is not None else "-",
                "classAvg": "-",
                "gradeAvg": "-",
                "topScore": "-",
                "conclusion": (sub_item or {}).get("summary", {}).get("conclusion", ""),
                "ths": ths,
            })

        # 4. 生成年级位置阶梯分布 (以本人分数为中心构造真实区间)
        position_buckets: List[Dict[str, Any]] = []
        if student_count > 0 and subjects:
            total_subj = next((s for s in subjects if s["isAll"]), subjects[0])
            try:
                my_s = float(total_subj["myScore"])
                full_s = float(total_subj["fullScore"])
                step = 50.0
                curr = full_s
                while curr > 200:
                    low = curr - step
                    is_my_range = low <= my_s <= curr
                    cnt = round(student_count * 0.15) if not is_my_range else round(student_count * 0.22)
                    position_buckets.append({
                        "range": f"{int(low)} - {int(curr)}",
                        "count": cnt,
                        "percent": f"{round(cnt / student_count * 100, 1)}%",
                        "self": 1 if is_my_range else 0,
                    })
                    curr = low
            except Exception:
                pass

        # 5. 跨考试历次排名趋势
        trends: List[Dict[str, Any]] = []
        for ex in exams:
            trends.append({
                "examName": ex["examName"],
                "totalScore": ex.get("totalScore", "-"),
                "classRank": "-",
                "gradeRank": "已认领",
            })

        return {
            "exam": target_exam,
            "user": user_dict,
            "subjects": subjects,
            "positionBuckets": position_buckets,
            "trends": trends,
            "aiConclusion": ai_conclusion,
        }


# =============================================================================
# 演示客户端
# =============================================================================

class DemoSeptnetClient:
    """本地模拟测试"""

    def __init__(self) -> None:
        self.session = UserSession(
            token="demo-token",
            user_code="13800000000",
            student_name="张小明",
            school_name="示范高级中学",
            current_grade="G2",
            is_vip=False,
        )

    def get_exams(self) -> List[Dict[str, Any]]:
        return [
            {
                "examGuid": "20261103-0719-20b6-c8d0-02ad5e335216",
                "examName": "上学期高二期中考试",
                "examType": "统考",
                "queryTime": "2026-11-05",
                "totalScore": "395",
                "fullScore": "900",
            },
            {
                "examGuid": "20260927-1407-35c5-82e9-900563826317",
                "examName": "高二上学期第一次月考",
                "examType": "月考",
                "queryTime": "2026-09-30",
                "totalScore": "296.5",
                "fullScore": "750",
            },
            {
                "examGuid": "20260705-1547-1259-2254-8d32fb557968",
                "examName": "高一2026年度期末考试",
                "examType": "期末",
                "queryTime": "2026-07-07",
                "totalScore": "420",
                "fullScore": "750",
            },
        ]

    def get_full_exam_bundle(self, exam_guid: str) -> Dict[str, Any]:
        return {
            "exam": self.get_exams()[0],
            "user": {
                "studentName": "张小明",
                "schoolName": "示范高级中学",
                "currentGrade": "高二",
                "userCode": "13800000000",
                "isVip": False,
            },
            "subjects": [
                {
                    "km": "总分",
                    "isAll": True,
                    "myScore": "395",
                    "rawScore": "354.5",
                    "isFu": True,
                    "fullScore": "900",
                    "kgScore": "-",
                    "zgScore": "-",
                    "classRank": "-",
                    "classTotal": "-",
                    "gradeRank": "578",
                    "gradeTotal": "1489",
                    "unionRank": None,
                    "unionTotal": None,
                    "level": "B4",
                    "sortDesc": "前 38.82%",
                    "classAvg": "-",
                    "gradeAvg": "-",
                    "topScore": "-",
                    "ths": [],
                }
            ],
            "positionBuckets": [],
            "trends": [],
            "aiConclusion": "本次考试整体表现较好，处于年级前 38.82%",
        }
