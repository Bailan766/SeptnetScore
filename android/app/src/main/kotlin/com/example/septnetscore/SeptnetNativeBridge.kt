package com.example.septnetscore

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.KeyFactory
import java.security.SecureRandom
import java.security.spec.X509EncodedKeySpec
import java.util.concurrent.Executors
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import kotlin.math.roundToInt

class SeptnetNativeBridge(private val context: Context, private val webView: WebView) {

    private val executor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())

    companion object {
        const val VERSION = "4.6.4"
        const val USER_AGENT = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 SeptnetStudent/4.6.4"
        const val RSA_PUB_B64 =
            "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDrjEcFVWu6mizSyP3fCCaWZ3BeTeuZx44H" +
            "HcWhzq6+FkueApOJbifi0VfaUO6S9eHvaJSEaCUFouD3cxr3fOk8RYQw1S1BcTscEbnqq/PC" +
            "uoj5vj12t/M3dbqTdNKCrufSukwBask+OOHenu9IJzkmvrPurLnIC3yDTy3Ix9YliQIDAQAB"
        val STATIC_AES_KEY = "c0f1a30cba2147949ee71cf71cba3c20".toByteArray(Charsets.UTF_8)
        const val PREFS_NAME = "septnet_session"
    }

    private var token = ""
    private var userCode = ""
    private var userGuid = ""
    private var studentName = ""
    private var schoolGuid = ""
    private var schoolName = ""
    private var ruCode = ""
    private var currentGrade = "G2"
    private var isVip = false

    private var rawAesKey: ByteArray? = null
    private var bkString: String? = null

    init {
        loadSavedSession()
    }

    private fun encodeCredential(value: String): String {
        val raw = (value + "{MTgyMjU2MDU0MjF7c3pvbmV9}").toByteArray(Charsets.UTF_8)
        return Base64.encodeToString(raw, Base64.NO_WRAP)
    }

    private fun initAesKey() {
        val randomBytes = ByteArray(32)
        SecureRandom().nextBytes(randomBytes)
        rawAesKey = randomBytes

        val aesKeyB64 = Base64.encodeToString(randomBytes, Base64.NO_WRAP)
        val rsaBytes = Base64.decode(RSA_PUB_B64, Base64.DEFAULT)
        val spec = X509EncodedKeySpec(rsaBytes)
        val kf = KeyFactory.getInstance("RSA")
        val pubKey = kf.generatePublic(spec)

        val cipher = Cipher.getInstance("RSA/ECB/PKCS1Padding")
        cipher.init(Cipher.ENCRYPT_MODE, pubKey)
        val encBytes = cipher.doFinal(aesKeyB64.toByteArray(Charsets.UTF_8))
        bkString = Base64.encodeToString(encBytes, Base64.NO_WRAP)
    }

    private fun performKeyExchange(): Boolean {
        if (rawAesKey == null || bkString == null) {
            initAesKey()
        }
        return try {
            val url = URL("https://szone-my.7net.cc/user")
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.setRequestProperty("Version", VERSION)
            conn.setRequestProperty("User-Agent", USER_AGENT)
            conn.setRequestProperty("check-webp", "false")
            conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
            conn.setRequestProperty("bk", bkString)
            if (token.isNotEmpty()) {
                conn.setRequestProperty("Token", token)
            }
            conn.doOutput = true
            conn.outputStream.write(ByteArray(0))
            val respCode = conn.responseCode
            respCode == 200
        } catch (e: Exception) {
            false
        }
    }

    private fun requestHttp(
        method: String,
        urlString: String,
        params: Map<String, String>? = null,
        isEncrypt: Boolean = false
    ): String {
        var finalUrl = urlString
        val headers = mutableMapOf<String, String>()
        headers["Version"] = VERSION
        headers["User-Agent"] = USER_AGENT
        headers["check-webp"] = "false"
        if (token.isNotEmpty()) {
            headers["Token"] = token
        }

        var postData = ByteArray(0)

        if (isEncrypt) {
            if (rawAesKey == null || bkString == null) {
                initAesKey()
                performKeyExchange()
            }
            headers["bk"] = bkString!!

            if (!params.isNullOrEmpty()) {
                val sb = StringBuilder()
                for ((k, v) in params) {
                    if (sb.isNotEmpty()) sb.append(";")
                    sb.append("$k=$v")
                }
                val plaintext = sb.toString().toByteArray(Charsets.UTF_8)
                val iv = ByteArray(12)
                SecureRandom().nextBytes(iv)

                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                val gcmSpec = GCMParameterSpec(128, iv)
                cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(rawAesKey, "AES"), gcmSpec)
                val ctAndTag = cipher.doFinal(plaintext)

                headers["bn"] = Base64.encodeToString(iv, Base64.NO_WRAP)
                headers["bp"] = Base64.encodeToString(ctAndTag, Base64.NO_WRAP)
            }
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
        } else {
            if (method.equals("GET", ignoreCase = true)) {
                if (!params.isNullOrEmpty()) {
                    val qsb = StringBuilder()
                    for ((k, v) in params) {
                        if (qsb.isNotEmpty()) qsb.append("&")
                        qsb.append(URLEncoder.encode(k, "UTF-8")).append("=").append(URLEncoder.encode(v, "UTF-8"))
                    }
                    val sep = if (finalUrl.contains("?")) "&" else "?"
                    finalUrl += "$sep$qsb"
                }
                headers["Content-Type"] = "application/json; charset=utf-8"
            } else {
                if (!params.isNullOrEmpty()) {
                    val psb = StringBuilder()
                    for ((k, v) in params) {
                        if (psb.isNotEmpty()) psb.append("&")
                        psb.append(URLEncoder.encode(k, "UTF-8")).append("=").append(URLEncoder.encode(v, "UTF-8"))
                    }
                    postData = psb.toString().toByteArray(Charsets.UTF_8)
                }
                headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
            }
        }

        val conn = URL(finalUrl).openConnection() as HttpURLConnection
        conn.requestMethod = method.uppercase()
        conn.connectTimeout = 12000
        conn.readTimeout = 12000
        for ((k, v) in headers) {
            conn.setRequestProperty(k, v)
        }

        if (method.equals("POST", ignoreCase = true)) {
            conn.doOutput = true
            conn.outputStream.write(postData)
        }

        val reader = BufferedReader(InputStreamReader(conn.inputStream, Charsets.UTF_8))
        val rawResponse = reader.readText()
        reader.close()

        val root = JSONObject(rawResponse)
        if (isEncrypt && root.has("data")) {
            val dataObj = root.optJSONObject("data")
            if (dataObj != null && dataObj.has("bn") && dataObj.has("content") && rawAesKey != null) {
                try {
                    val iv = Base64.decode(dataObj.getString("bn"), Base64.DEFAULT)
                    val ctAndTag = Base64.decode(dataObj.getString("content"), Base64.DEFAULT)
                    val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                    val gcmSpec = GCMParameterSpec(128, iv)
                    cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(rawAesKey, "AES"), gcmSpec)
                    val pt = String(cipher.doFinal(ctAndTag), Charsets.UTF_8)
                    root.put("data", JSONObject(pt))
                } catch (_: Exception) {}
            }
        }

        if (root.has("data")) {
            val dataObj = root.optJSONObject("data")
            if (dataObj != null && dataObj.optBoolean("isEncrypt") && dataObj.has("content")) {
                try {
                    val ct = Base64.decode(dataObj.getString("content"), Base64.DEFAULT)
                    val cipher = Cipher.getInstance("AES/ECB/PKCS5Padding")
                    cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(STATIC_AES_KEY, "AES"))
                    val pt = String(cipher.doFinal(ct), Charsets.UTF_8)
                    root.put("data", JSONObject(pt))
                } catch (_: Exception) {}
            }
        }

        return root.toString()
    }

    private fun loadSavedSession() {
        val sp = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        token = sp.getString("token", "") ?: ""
        userCode = sp.getString("userCode", "") ?: ""
        userGuid = sp.getString("userGuid", "") ?: ""
        studentName = sp.getString("studentName", "") ?: ""
        schoolGuid = sp.getString("schoolGuid", "") ?: ""
        schoolName = sp.getString("schoolName", "") ?: ""
        ruCode = sp.getString("ruCode", "") ?: ""
        currentGrade = sp.getString("currentGrade", "G2") ?: "G2"
        isVip = sp.getBoolean("isVip", false)

        val rawAesB64 = sp.getString("rawAesKeyB64", "") ?: ""
        if (rawAesB64.isNotEmpty()) {
            try {
                rawAesKey = Base64.decode(rawAesB64, Base64.DEFAULT)
                bkString = sp.getString("bk", "")
            } catch (_: Exception) {}
        }
    }

    private fun saveSessionToPrefs() {
        val sp = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        sp.edit().apply {
            putString("token", token)
            putString("userCode", userCode)
            putString("userGuid", userGuid)
            putString("studentName", studentName)
            putString("schoolGuid", schoolGuid)
            putString("schoolName", schoolName)
            putString("ruCode", ruCode)
            putString("currentGrade", currentGrade)
            putBoolean("isVip", isVip)
            if (rawAesKey != null) {
                putString("rawAesKeyB64", Base64.encodeToString(rawAesKey, Base64.NO_WRAP))
                putString("bk", bkString)
            }
            apply()
        }
    }

    @JavascriptInterface
    fun getSavedSession(): String {
        val obj = JSONObject()
        obj.put("token", token)
        obj.put("userCode", userCode)
        obj.put("studentName", studentName)
        obj.put("schoolName", schoolName)
        obj.put("currentGrade", currentGrade)
        obj.put("isVip", isVip)
        return obj.toString()
    }

    @JavascriptInterface
    fun login(uCode: String, pwd: String) {
        executor.execute {
            try {
                val params = mapOf(
                    "userCode" to uCode,
                    "password" to encodeCredential(pwd)
                )
                val respStr = requestHttp("POST", "https://szone-my.7net.cc/login", params)
                val respObj = JSONObject(respStr)
                val dataObj = respObj.optJSONObject("data")
                val t = dataObj?.optString("token") ?: ""
                if (t.isEmpty()) {
                    callbackJs("onNativeLoginResult", JSONObject().apply {
                        put("ok", false)
                        put("message", respObj.optString("message", "登录失败"))
                    })
                    return@execute
                }

                token = t
                userCode = uCode
                initAesKey()
                performKeyExchange()

                // 获取用户信息
                val uInfoStr = requestHttp("GET", "https://szone-my.7net.cc/userInfo/GetUserInfo", null, isEncrypt = true)
                val uInfoRoot = JSONObject(uInfoStr)
                val uData = uInfoRoot.optJSONObject("data")
                if (uData != null) {
                    userGuid = uData.optString("userGuid", "")
                    studentName = uData.optString("studentName", "")
                    schoolGuid = uData.optString("schoolGuid", "")
                    schoolName = uData.optString("schoolName", "")
                    ruCode = uData.optString("ruCode", "")
                    val gradeRaw = uData.optString("currentGrade", "G2")
                    currentGrade = gradeRaw.uppercase()
                    isVip = uData.optBoolean("isVip", false)
                }

                saveSessionToPrefs()

                // 获取考试列表与首场考试
                val examsArr = fetchClaimExamsList()
                val bundleObj = fetchExamBundleInternal(if (examsArr.length() > 0) examsArr.getJSONObject(0).optString("examGuid") else "")

                val finalResult = JSONObject().apply {
                    put("ok", true)
                    put("token", token)
                    put("exams", examsArr)
                    put("bundle", bundleObj)
                }
                callbackJs("onNativeLoginResult", finalResult)
            } catch (e: Exception) {
                callbackJs("onNativeLoginResult", JSONObject().apply {
                    put("ok", false)
                    put("message", e.message ?: "网络错误")
                })
            }
        }
    }

    private fun fetchClaimExamsList(): JSONArray {
        val params = mapOf(
            "startIndex" to "0",
            "rows" to "25",
            "schoolGuid" to schoolGuid,
            "grade" to currentGrade
        )
        val respStr = requestHttp("GET", "https://szone-score.7net.cc/exam/getClaimExams", params)
        val respObj = JSONObject(respStr)
        val dataObj = respObj.optJSONObject("data")
        val listArr = dataObj?.optJSONArray("list") ?: JSONArray()
        val resultArr = JSONArray()

        for (i in 0 until listArr.length()) {
            val item = listArr.getJSONObject(i)
            val eg = item.optString("examGuid", item.optString("guid", ""))
            if (eg.isNotEmpty()) {
                val exObj = JSONObject().apply {
                    put("examGuid", eg)
                    put("examName", item.optString("examName", "未命名考试"))
                    put("examType", item.optString("examType", if (item.optBoolean("isUnion")) "联考" else "统考"))
                    put("queryTime", item.optString("queryTime", item.optString("examTime", "-")))
                    put("totalScore", item.optString("score", item.optString("totalScore", "-")))
                    put("fullScore", item.optInt("fullScore", 750))
                    put("isUnion", item.optBoolean("isUnion", false))
                }
                resultArr.put(exObj)
            }
        }
        return resultArr
    }

    @JavascriptInterface
    fun fetchExamBundle(examGuid: String) {
        executor.execute {
            try {
                val bundle = fetchExamBundleInternal(examGuid)
                val res = JSONObject().apply {
                    put("ok", true)
                    put("bundle", bundle)
                }
                callbackJs("onNativeBundleResult", res)
            } catch (e: Exception) {
                callbackJs("onNativeBundleResult", JSONObject().apply {
                    put("ok", false)
                    put("message", e.message ?: "拉取失败")
                })
            }
        }
    }

    private fun fetchExamBundleInternal(examGuid: String): JSONObject {
        val userObj = JSONObject().apply {
            put("studentName", studentName)
            put("schoolName", schoolName)
            put("currentGrade", currentGrade)
            put("userCode", userCode)
            put("isVip", isVip)
        }

        val examObj = JSONObject().apply {
            put("examGuid", examGuid)
            put("examName", "上学期高二期中考试")
            put("queryTime", "2026-11-05")
        }

        var studentCount = 1489
        var aiConclusion = ""
        val subMap = mutableMapOf<String, JSONObject>()

        // 1. Question/Subjects
        try {
            val params = mapOf(
                "examGuid" to examGuid,
                "schoolGuid" to schoolGuid,
                "grade" to currentGrade,
                "schoolRuCode" to ruCode
            )
            val subStr = requestHttp("POST", "https://szone-score.7net.cc/Question/Subjects", params, isEncrypt = true)
            val subRoot = JSONObject(subStr)
            val subData = subRoot.optJSONObject("data")
            if (subData != null) {
                studentCount = subData.optJSONObject("exam_info")?.optString("studentCount")?.toIntOrNull() ?: 1489
                val sList = subData.optJSONArray("list") ?: JSONArray()
                for (i in 0 until sList.length()) {
                    val s = sList.getJSONObject(i)
                    val km = s.optString("km")
                    if (km.isNotEmpty()) {
                        subMap[km] = s
                        if (km == "总分") {
                            aiConclusion = s.optJSONObject("summary")?.optString("conclusion", "") ?: ""
                        }
                    }
                }
            }
        } catch (_: Exception) {}

        // 2. Question/ScoreReport
        val srMap = mutableMapOf<String, JSONObject>()
        try {
            val params = mapOf(
                "examGuid" to examGuid,
                "schoolGuid" to schoolGuid,
                "grade" to currentGrade,
                "schoolRuCode" to ruCode,
                "km" to "总分"
            )
            val srStr = requestHttp("POST", "https://szone-score.7net.cc/Question/ScoreReport", params, isEncrypt = true)
            val srRoot = JSONObject(srStr)
            val srData = srRoot.optJSONObject("data")
            val srList = srData?.optJSONArray("km_list") ?: JSONArray()
            for (i in 0 until srList.length()) {
                val item = srList.getJSONObject(i)
                val km = item.optString("km")
                if (km.isNotEmpty()) {
                    srMap[km] = item
                }
            }
        } catch (_: Exception) {}

        val subjectsArr = JSONArray()
        val orderedKms = listOf("总分", "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理")

        for (km in orderedKms) {
            val sr = srMap[km]
            val sub = subMap[km]
            if (sr == null && sub == null) continue

            if (sr != null && (sr.optString("score") == "缺考" || sr.optInt("kmTag") == -100)) continue
            if (sub != null && sub.optInt("code") == -1) continue

            val si = sub?.optJSONObject("scoreInfo")
            val sortDesc = si?.optString("sortDesc", "") ?: ""
            var pct: Double? = null
            if (sortDesc.contains(",")) {
                pct = sortDesc.split(",")[0].toDoubleOrNull()
            }

            val calcRank = if (pct != null && studentCount > 0) {
                ((studentCount * pct) / 100.0).roundToInt().toString()
            } else "-"

            val isFu = sr?.optInt("isFu", 0) == 1
            val rawScore = sr?.optString("score", "-") ?: "-"
            val fuScore = sr?.optString("fuScore", rawScore) ?: rawScore
            val displayScore = if (isFu && fuScore.isNotEmpty() && fuScore != "0") fuScore else rawScore
            val fullScore = sr?.optString("fullScore", "100") ?: "100"
            val ratingLevel = sr?.optString("grade", si?.optString("grade", "-") ?: "-") ?: "-"

            val subJson = JSONObject().apply {
                put("km", km)
                put("isAll", km == "总分")
                put("myScore", displayScore)
                put("rawScore", rawScore)
                put("isFu", isFu)
                put("fullScore", fullScore)
                put("gradeRank", calcRank)
                put("gradeTotal", studentCount.toString())
                put("level", ratingLevel)
                put("sortDesc", if (pct != null) "前 $pct%" else "-")
                put("ths", JSONArray())
            }
            subjectsArr.put(subJson)
        }

        return JSONObject().apply {
            put("exam", examObj)
            put("user", userObj)
            put("subjects", subjectsArr)
            put("aiConclusion", aiConclusion)
            put("positionBuckets", JSONArray())
            put("trends", JSONArray())
        }
    }

    private fun callbackJs(functionName: String, jsonParam: JSONObject) {
        mainHandler.post {
            val escaped = jsonParam.toString().replace("\\", "\\\\").replace("'", "\\'")
            webView.evaluateJavascript("$functionName('$escaped')", null)
        }
    }
}
