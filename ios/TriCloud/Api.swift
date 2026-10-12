import Foundation
import Security

// 直连 TriCloud 面板 API（Bearer token），对应 Android 版 Api.java。
// 服务器地址由用户在登录页填写，存 UserDefaults；token 存 Keychain。代码中不含任何域名。

typealias JObj = [String: Any]
typealias JArr = [Any]

func jobj(_ o: Any?) -> JObj { (o as? JObj) ?? [:] }   // Api.obj
func jarr(_ o: Any?) -> JArr { (o as? JArr) ?? [] }     // Api.arr

/// 把任意 JSON 值转成与 Android org.json 接近的字符串。
func jsonText(_ v: Any?) -> String? {
    guard let v = v, !(v is NSNull) else { return nil }
    if let s = v as? String { return s }
    if let n = v as? NSNumber {
        if CFGetTypeID(n) == CFBooleanGetTypeID() { return n.boolValue ? "true" : "false" }
        if CFNumberIsFloatType(n as CFNumber) {
            let d = n.doubleValue
            return "\(d)"
        }
        return "\(n.int64Value)"
    }
    if JSONSerialization.isValidJSONObject(v), let d = try? JSONSerialization.data(withJSONObject: v), let s = String(data: d, encoding: .utf8) {
        return s
    }
    return "\(v)"
}

extension Dictionary where Key == String, Value == Any {
    func has(_ k: String) -> Bool { self[k] != nil }
    /// 与 org.json 一致：缺失或 JSON null 都算 null。
    func isNull(_ k: String) -> Bool { self[k] == nil || self[k] is NSNull }
    func opt(_ k: String) -> Any? { isNull(k) ? nil : self[k] }
    func optString(_ k: String, _ def: String = "") -> String { jsonText(opt(k)) ?? def }
    func optInt(_ k: String, _ def: Int = 0) -> Int {
        guard let v = opt(k) else { return def }
        if let n = v as? NSNumber { return n.intValue }
        if let s = v as? String, let d = Double(s.trimmingCharacters(in: .whitespaces)) { return Int(d) }
        return def
    }
    func optLong(_ k: String) -> Int64 {
        guard let v = opt(k) else { return 0 }
        if let n = v as? NSNumber { return n.int64Value }
        if let s = v as? String, let d = Double(s) { return Int64(d) }
        return 0
    }
    func optDouble(_ k: String, _ def: Double = .nan) -> Double {
        guard let v = opt(k) else { return def }
        if let n = v as? NSNumber { return n.doubleValue }
        if let s = v as? String, let d = Double(s.trimmingCharacters(in: .whitespaces)) { return d }
        return def
    }
    func optBoolean(_ k: String, _ def: Bool = false) -> Bool {
        guard let v = opt(k) else { return def }
        if let n = v as? NSNumber { return n.boolValue }
        if let s = v as? String { if s.lowercased() == "true" { return true }; if s.lowercased() == "false" { return false } }
        return def
    }
    func optJSONObject(_ k: String) -> JObj? { self[k] as? JObj }
    func optJSONArray(_ k: String) -> JArr? { self[k] as? JArr }
}

extension Array where Element == Any {
    func obj(_ i: Int) -> JObj { i >= 0 && i < count ? jobj(self[i]) : [:] }
    func string(_ i: Int) -> String { i >= 0 && i < count ? (jsonText(self[i]) ?? "") : "" }
}

/// BaseActivity.str：null / 缺失 / 空串 都返回默认值。
func str(_ o: JObj?, _ k: String, _ def: String) -> String {
    guard let o = o, !o.isNull(k) else { return def }
    let v = o.optString(k, def)
    return v.isEmpty ? def : v
}

func join(_ a: JArr?) -> String {
    guard let a = a else { return "" }
    return (0..<a.count).map { a.string($0) }.joined(separator: ", ")
}

func fmt2(_ d: Double) -> String { String(format: "%.2f", d) }

/// java.net.URLEncoder.encode（表单编码：空格 → +）。
func enc(_ s: String?) -> String {
    let safe = Set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._*".utf8)
    var out = ""
    for b in (s ?? "").utf8 {
        if safe.contains(b) { out.append(Character(UnicodeScalar(b))) }
        else if b == 0x20 { out.append("+") }
        else { out += String(format: "%%%02X", b) }
    }
    return out
}

/// 秒级时间戳转 36 进制（Long.toString(x, 36)）。
func base36Now() -> String { String(Int(Date().timeIntervalSince1970), radix: 36) }

// MARK: - 存储

enum Keychain {
    private static let service = "com.tricloud.app"

    static func get(_ account: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: account, kSecReturnData as String: true,
                                kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func set(_ account: String, _ value: String) {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                   kSecAttrAccount as String: account]
        SecItemDelete(base as CFDictionary)
        if value.isEmpty { return }
        var add = base
        add[kSecValueData as String] = Data(value.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }
}

enum Prefs {
    static func get(_ k: String, _ def: String) -> String { UserDefaults.standard.string(forKey: "pref_" + k) ?? def }
    static func set(_ k: String, _ v: String) { UserDefaults.standard.set(v, forKey: "pref_" + k) }
}

// MARK: - API

struct ApiError: Error {
    let code: Int
    let msg: String
    var guardList: JArr? = nil   // v1.2 免费额度护栏：409 时的警告列表
}

enum Api {
    static var server: String { UserDefaults.standard.string(forKey: "server") ?? "" }
    static var token: String { Keychain.get("token") ?? "" }

    static func save(server: String, token: String) {
        UserDefaults.standard.set(server, forKey: "server")
        Keychain.set("token", token)
    }

    static func logout() { Keychain.set("token", "") }

    private static let session: URLSession = {
        let c = URLSessionConfiguration.default
        c.timeoutIntervalForRequest = 120
        c.timeoutIntervalForResource = 180
        c.httpCookieStorage = nil
        c.httpShouldSetCookies = false
        return URLSession(configuration: c)
    }()

    /// 异步调用，回调在主线程：成功返回 JObj / JArr，失败返回 Error。
    static func call(_ method: String, _ path: String, _ body: JObj?, _ done: @escaping (Result<Any, Error>) -> Void) {
        guard let url = URL(string: server + "/api" + path) else {
            done(.failure(ApiError(code: 0, msg: "地址无效")))
            return
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        var payload: Data? = nil
        if let b = body {
            payload = (try? JSONSerialization.data(withJSONObject: b)) ?? Data("{}".utf8)
        } else if method != "GET" && method != "DELETE" {
            payload = Data("{}".utf8)
        }
        if let p = payload {
            req.httpBody = p
            req.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        }
        session.dataTask(with: req) { data, resp, err in
            let result: Result<Any, Error>
            if let err = err {
                result = .failure(ApiError(code: 0, msg: err.localizedDescription))
            } else {
                let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
                let d = data ?? Data()
                let j: Any = d.isEmpty ? JObj() : ((try? JSONSerialization.jsonObject(with: d, options: [.fragmentsAllowed])) ?? JObj())
                if (200..<300).contains(code) {
                    result = .success(j)
                } else {
                    var msg = "HTTP \(code)"
                    var guardList: JArr? = nil
                    if let o = j as? JObj, let det = o["detail"], !(det is NSNull) {
                        if let dd = det as? JObj {
                            msg = dd.optString("msg", msg)
                            guardList = dd.optJSONArray("guard")
                        } else if let t = jsonText(det) {
                            msg = t
                        }
                    }
                    result = .failure(ApiError(code: code, msg: msg, guardList: guardList))
                }
            }
            DispatchQueue.main.async { done(result) }
        }.resume()
    }
    /// 二进制请求：下载加密备份（返回数据 + 文件名）、上传对象存储文件（原始 body）。
    static func raw(_ method: String, _ path: String, json: JObj? = nil, data: Data? = nil,
                    _ done: @escaping (Result<(Data, String), Error>) -> Void) {
        guard let url = URL(string: server + "/api" + path) else {
            done(.failure(ApiError(code: 0, msg: "地址无效")))
            return
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = 600
        req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        if let j = json {
            req.httpBody = (try? JSONSerialization.data(withJSONObject: j)) ?? Data("{}".utf8)
            req.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        } else if let d = data {
            req.httpBody = d
            req.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        }
        session.dataTask(with: req) { d, resp, err in
            let result: Result<(Data, String), Error>
            if let err = err {
                result = .failure(ApiError(code: 0, msg: err.localizedDescription))
            } else {
                let http = resp as? HTTPURLResponse
                let code = http?.statusCode ?? 0
                let body = d ?? Data()
                if (200..<300).contains(code) {
                    var fn = "download.bin"
                    if let cd = http?.value(forHTTPHeaderField: "Content-Disposition"), let r = cd.range(of: "filename=\"") {
                        let rest = cd[r.upperBound...]
                        fn = String(rest.prefix { $0 != "\"" })
                    }
                    result = .success((body, fn))
                } else {
                    var msg = "HTTP \(code)"
                    if let o = (try? JSONSerialization.jsonObject(with: body)) as? JObj, let t = jsonText(o["detail"]) { msg = t }
                    result = .failure(ApiError(code: code, msg: msg))
                }
            }
            DispatchQueue.main.async { done(result) }
        }.resume()
    }
}
