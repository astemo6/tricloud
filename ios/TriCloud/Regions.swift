import Foundation

/// 区域代码 → 中文城市名，与 Web core.js 的 REGION_CITY / OCI_KEY 相同（AWS / OCI / Azure）。显示用 label()，提交仍用纯代码。
enum Regions {
    static let city: [String: String] = [
        "us-east-1": "弗吉尼亚北部", "us-east-2": "俄亥俄", "us-west-1": "加州北部", "us-west-2": "俄勒冈", "af-south-1": "开普敦", "ap-east-1": "香港",
        "ap-east-2": "台北", "ap-south-1": "孟买", "ap-south-2": "海得拉巴", "ap-northeast-1": "东京", "ap-northeast-2": "首尔", "ap-northeast-3": "大阪",
        "ap-southeast-1": "新加坡", "ap-southeast-2": "悉尼", "ap-southeast-3": "雅加达", "ap-southeast-4": "墨尔本", "ap-southeast-5": "吉隆坡", "ap-southeast-6": "新西兰",
        "ap-southeast-7": "曼谷", "ca-central-1": "蒙特利尔", "ca-west-1": "卡尔加里", "eu-central-1": "法兰克福", "eu-central-2": "苏黎世", "eu-north-1": "斯德哥尔摩",
        "eu-south-1": "米兰", "eu-south-2": "西班牙", "eu-west-1": "爱尔兰", "eu-west-2": "伦敦", "eu-west-3": "巴黎", "il-central-1": "特拉维夫",
        "me-central-1": "阿联酋", "me-south-1": "巴林", "mx-central-1": "墨西哥", "sa-east-1": "圣保罗", "cn-north-1": "北京", "cn-northwest-1": "宁夏",
        "us-gov-west-1": "GovCloud 西部", "us-gov-east-1": "GovCloud 东部", "ap-sydney-1": "悉尼", "ap-melbourne-1": "墨尔本", "sa-saopaulo-1": "圣保罗", "sa-vinhedo-1": "维涅杜",
        "ca-montreal-1": "蒙特利尔", "ca-toronto-1": "多伦多", "sa-santiago-1": "圣地亚哥", "sa-valparaiso-1": "瓦尔帕莱索", "sa-bogota-1": "波哥大", "eu-paris-1": "巴黎",
        "eu-marseille-1": "马赛", "eu-frankfurt-1": "法兰克福", "ap-hyderabad-1": "海得拉巴", "ap-mumbai-1": "孟买", "ap-batam-1": "巴淡岛", "il-jerusalem-1": "耶路撒冷",
        "eu-milan-1": "米兰", "eu-turin-1": "都灵", "ap-osaka-1": "大阪", "ap-tokyo-1": "东京", "ap-kulai-2": "古来", "mx-queretaro-1": "克雷塔罗",
        "mx-monterrey-1": "蒙特雷", "af-casablanca-1": "卡萨布兰卡", "eu-amsterdam-1": "阿姆斯特丹", "me-riyadh-1": "利雅得", "me-jeddah-1": "吉达", "eu-jovanovac-1": "约瓦诺瓦茨",
        "ap-singapore-1": "新加坡", "ap-singapore-2": "新加坡西", "af-johannesburg-1": "约翰内斯堡", "ap-seoul-1": "首尔", "ap-chuncheon-1": "春川", "eu-madrid-1": "马德里",
        "eu-madrid-3": "马德里 3", "eu-stockholm-1": "斯德哥尔摩", "eu-zurich-1": "苏黎世", "me-abudhabi-1": "阿布扎比", "me-dubai-1": "迪拜", "uk-london-1": "伦敦",
        "uk-cardiff-1": "纽波特", "us-ashburn-1": "阿什本", "us-chicago-1": "芝加哥", "us-phoenix-1": "凤凰城", "us-sanjose-1": "圣何塞", "eastasia": "香港",
        "southeastasia": "新加坡", "japaneast": "东日本", "japanwest": "西日本", "koreacentral": "韩国中部", "koreasouth": "韩国南部", "australiaeast": "新南威尔士",
        "australiasoutheast": "维多利亚", "australiacentral": "堪培拉", "centralindia": "浦那", "southindia": "金奈", "westindia": "孟买", "eastus": "弗吉尼亚",
        "eastus2": "弗吉尼亚 2", "westus": "加州", "westus2": "华盛顿州", "westus3": "亚利桑那", "centralus": "爱荷华", "northcentralus": "伊利诺伊",
        "southcentralus": "德克萨斯", "westcentralus": "怀俄明", "canadacentral": "多伦多", "canadaeast": "魁北克", "brazilsouth": "圣保罗", "mexicocentral": "克雷塔罗",
        "northeurope": "爱尔兰", "westeurope": "荷兰", "uksouth": "伦敦", "ukwest": "加的夫", "francecentral": "巴黎", "germanywestcentral": "法兰克福",
        "switzerlandnorth": "苏黎世", "norwayeast": "奥斯陆", "swedencentral": "耶夫勒", "polandcentral": "华沙", "italynorth": "米兰", "spaincentral": "马德里",
        "uaenorth": "迪拜", "qatarcentral": "多哈", "israelcentral": "以色列", "southafricanorth": "约翰内斯堡", "indonesiacentral": "雅加达", "malaysiawest": "吉隆坡",
        "newzealandnorth": "奥克兰"
    ]
    static let ociKey: [String: String] = [
        "SYD": "ap-sydney-1", "MEL": "ap-melbourne-1", "GRU": "sa-saopaulo-1", "VCP": "sa-vinhedo-1", "YUL": "ca-montreal-1", "YYZ": "ca-toronto-1", "SCL": "sa-santiago-1", "VAP": "sa-valparaiso-1",
        "BOG": "sa-bogota-1", "CDG": "eu-paris-1", "MRS": "eu-marseille-1", "FRA": "eu-frankfurt-1", "HYD": "ap-hyderabad-1", "BOM": "ap-mumbai-1", "HSG": "ap-batam-1", "MTZ": "il-jerusalem-1",
        "LIN": "eu-milan-1", "NRQ": "eu-turin-1", "KIX": "ap-osaka-1", "NRT": "ap-tokyo-1", "JBP": "ap-kulai-2", "QRO": "mx-queretaro-1", "MTY": "mx-monterrey-1", "LEJ": "af-casablanca-1",
        "AMS": "eu-amsterdam-1", "RUH": "me-riyadh-1", "JED": "me-jeddah-1", "BEG": "eu-jovanovac-1", "SIN": "ap-singapore-1", "XSP": "ap-singapore-2", "JNB": "af-johannesburg-1", "ICN": "ap-seoul-1",
        "YNY": "ap-chuncheon-1", "MAD": "eu-madrid-1", "ORF": "eu-madrid-3", "ARN": "eu-stockholm-1", "ZRH": "eu-zurich-1", "AUH": "me-abudhabi-1", "DXB": "me-dubai-1", "LHR": "uk-london-1",
        "CWL": "uk-cardiff-1", "IAD": "us-ashburn-1", "ORD": "us-chicago-1", "PHX": "us-phoenix-1", "SJC": "us-sanjose-1"
    ]

    private static func firstGroup(_ pattern: String, _ s: String, _ ci: Bool = false) -> String? {
        guard let re = try? NSRegularExpression(pattern: pattern, options: ci ? [.caseInsensitive] : []) else { return nil }
        let ns = s as NSString
        guard let m = re.firstMatch(in: s, options: [], range: NSRange(location: 0, length: ns.length)), m.numberOfRanges > 1 else { return nil }
        let r = m.range(at: 1)
        return r.location == NSNotFound ? nil : ns.substring(with: r)
    }

    /// 城市名；未知返回 ""。也识别 AWS 可用区 ap-northeast-1a、OCI AD AP-TOKYO-1-AD-1 / Uocm:NRT-AD-1。
    static func cityOf(_ code: String?) -> String {
        let raw = (code ?? "").trimmingCharacters(in: .whitespaces)
        let c = raw.lowercased()
        if c.isEmpty || c == "null" { return "" }
        if let v = city[c] { return v }
        if let g = firstGroup("^([a-z]{2}(?:-[a-z]+)+-\\d+)[a-z]$", c), let v = city[g] { return v }
        if let g = firstGroup("([a-z]+-[a-z]+-\\d+)-ad-\\d+$", c), let v = city[g] { return v }
        if let g = firstGroup("(?:^|:)([A-Za-z]{3})-AD-\\d+$", raw, true), let r = ociKey[g.uppercased()], let v = city[r] { return v }
        return ""
    }

    /// 「ap-northeast-1 · 东京」；未知只返回代码。
    static func label(_ code: String?) -> String {
        let s = code ?? ""
        let c = cityOf(s)
        return c.isEmpty ? s : s + " · " + c
    }

    /// 总览卡片（/accounts/{id}/overview 的 regions，已按台数降序）：1 个区域「ap-northeast-1 · 东京」，多个「东京 等 2 个区域」，没有返回 ""。与 core.js regionsBrief 相同。
    static func brief(_ regions: JArr?) -> String {
        guard let r = regions, !r.isEmpty else { return "" }
        let first = r.obj(0).optString("region")
        if r.count == 1 { return label(first) }
        let c = cityOf(first)
        return (c.isEmpty ? first : c) + " 等 \(r.count) 个区域"
    }

    /// 多区域分布「东京 2 · 新加坡 1」（城市名未知时用代码）。与 core.js regionsDist 相同。
    static func dist(_ regions: JArr?) -> String {
        guard let r = regions else { return "" }
        return (0..<r.count).map { i -> String in
            let code = r.obj(i).optString("region")
            let c = cityOf(code)
            return (c.isEmpty ? code : c) + " \(r.obj(i).optInt("count"))"
        }.joined(separator: " · ")
    }

    /// 实例数「3 台（运行 2）· EC2 2 · Lightsail 1」，与 core.js overviewCount 相同。
    static func count(_ o: JObj) -> String {
        var parts: [String] = []
        if o.optString("provider") == "aws" {
            let ls = o.optInt("lightsail")
            parts.append("EC2 \(o.optInt("ec2"))")
            parts.append("Lightsail " + (o.optBoolean("lightsail_failed") ? (ls > 0 ? "\(ls)（部分区域失败）" : "查询失败") : "\(ls)"))
        }
        let err = o.optJSONArray("errors") ?? []
        if !err.isEmpty { parts.append("\(err.count) 个区域查询失败") }
        return "\(o.optInt("total")) 台（运行 \(o.optInt("running"))）" + (parts.isEmpty ? "" : "· " + parts.joined(separator: " · "))
    }
}
