package com.tricloud.app;

import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** 区域代码 → 中文城市名，与 Web core.js 的 REGION_CITY / OCI_KEY 相同（AWS / OCI / Azure）。显示用 label()，提交仍用纯代码。 */
final class Regions {
    private Regions() { }
    static final Map<String, String> CITY = new HashMap<>();
    static final Map<String, String> CITY_EN = new HashMap<>();
    static boolean EN = false;

    private static String cityName(String code) {
        String v = EN ? CITY_EN.get(code) : CITY.get(code);
        return v != null ? v : CITY.get(code);
    }
    private static boolean hasCity(String code) { return cityName(code) != null; }
    static final Map<String, String> OCI_KEY = new HashMap<>();

    private static void put(Map<String, String> m, String... kv) { for (int i = 0; i + 1 < kv.length; i += 2) m.put(kv[i], kv[i + 1]); }

    static {
        put(CITY, "us-east-1", "弗吉尼亚北部", "us-east-2", "俄亥俄", "us-west-1", "加州北部", "us-west-2", "俄勒冈", "af-south-1", "开普敦", "ap-east-1", "香港");
        put(CITY, "ap-east-2", "台北", "ap-south-1", "孟买", "ap-south-2", "海得拉巴", "ap-northeast-1", "东京", "ap-northeast-2", "首尔", "ap-northeast-3", "大阪");
        put(CITY, "ap-southeast-1", "新加坡", "ap-southeast-2", "悉尼", "ap-southeast-3", "雅加达", "ap-southeast-4", "墨尔本", "ap-southeast-5", "吉隆坡", "ap-southeast-6", "新西兰");
        put(CITY, "ap-southeast-7", "曼谷", "ca-central-1", "蒙特利尔", "ca-west-1", "卡尔加里", "eu-central-1", "法兰克福", "eu-central-2", "苏黎世", "eu-north-1", "斯德哥尔摩");
        put(CITY, "eu-south-1", "米兰", "eu-south-2", "西班牙", "eu-west-1", "爱尔兰", "eu-west-2", "伦敦", "eu-west-3", "巴黎", "il-central-1", "特拉维夫");
        put(CITY, "me-central-1", "阿联酋", "me-south-1", "巴林", "mx-central-1", "墨西哥", "sa-east-1", "圣保罗", "cn-north-1", "北京", "cn-northwest-1", "宁夏");
        put(CITY, "us-gov-west-1", "GovCloud 西部", "us-gov-east-1", "GovCloud 东部", "ap-sydney-1", "悉尼", "ap-melbourne-1", "墨尔本", "sa-saopaulo-1", "圣保罗", "sa-vinhedo-1", "维涅杜");
        put(CITY, "ca-montreal-1", "蒙特利尔", "ca-toronto-1", "多伦多", "sa-santiago-1", "圣地亚哥", "sa-valparaiso-1", "瓦尔帕莱索", "sa-bogota-1", "波哥大", "eu-paris-1", "巴黎");
        put(CITY, "eu-marseille-1", "马赛", "eu-frankfurt-1", "法兰克福", "ap-hyderabad-1", "海得拉巴", "ap-mumbai-1", "孟买", "ap-batam-1", "巴淡岛", "il-jerusalem-1", "耶路撒冷");
        put(CITY, "eu-milan-1", "米兰", "eu-turin-1", "都灵", "ap-osaka-1", "大阪", "ap-tokyo-1", "东京", "ap-kulai-2", "古来", "mx-queretaro-1", "克雷塔罗");
        put(CITY, "mx-monterrey-1", "蒙特雷", "af-casablanca-1", "卡萨布兰卡", "eu-amsterdam-1", "阿姆斯特丹", "me-riyadh-1", "利雅得", "me-jeddah-1", "吉达", "eu-jovanovac-1", "约瓦诺瓦茨");
        put(CITY, "ap-singapore-1", "新加坡", "ap-singapore-2", "新加坡西", "af-johannesburg-1", "约翰内斯堡", "ap-seoul-1", "首尔", "ap-chuncheon-1", "春川", "eu-madrid-1", "马德里");
        put(CITY, "eu-madrid-3", "马德里 3", "eu-stockholm-1", "斯德哥尔摩", "eu-zurich-1", "苏黎世", "me-abudhabi-1", "阿布扎比", "me-dubai-1", "迪拜", "uk-london-1", "伦敦");
        put(CITY, "uk-cardiff-1", "纽波特", "us-ashburn-1", "阿什本", "us-chicago-1", "芝加哥", "us-phoenix-1", "凤凰城", "us-sanjose-1", "圣何塞", "eastasia", "香港");
        put(CITY, "southeastasia", "新加坡", "japaneast", "东日本", "japanwest", "西日本", "koreacentral", "韩国中部", "koreasouth", "韩国南部", "australiaeast", "新南威尔士");
        put(CITY, "australiasoutheast", "维多利亚", "australiacentral", "堪培拉", "centralindia", "浦那", "southindia", "金奈", "westindia", "孟买", "eastus", "弗吉尼亚");
        put(CITY, "eastus2", "弗吉尼亚 2", "westus", "加州", "westus2", "华盛顿州", "westus3", "亚利桑那", "centralus", "爱荷华", "northcentralus", "伊利诺伊");
        put(CITY, "southcentralus", "德克萨斯", "westcentralus", "怀俄明", "canadacentral", "多伦多", "canadaeast", "魁北克", "brazilsouth", "圣保罗", "mexicocentral", "克雷塔罗");
        put(CITY, "northeurope", "爱尔兰", "westeurope", "荷兰", "uksouth", "伦敦", "ukwest", "加的夫", "francecentral", "巴黎", "germanywestcentral", "法兰克福");
        put(CITY, "switzerlandnorth", "苏黎世", "norwayeast", "奥斯陆", "swedencentral", "耶夫勒", "polandcentral", "华沙", "italynorth", "米兰", "spaincentral", "马德里");
        put(CITY, "uaenorth", "迪拜", "qatarcentral", "多哈", "israelcentral", "以色列", "southafricanorth", "约翰内斯堡", "indonesiacentral", "雅加达", "malaysiawest", "吉隆坡");
        put(CITY, "newzealandnorth", "奥克兰");
        put(CITY_EN, "us-east-1", "N. Virginia", "us-east-2", "Ohio", "us-west-1", "N. California", "us-west-2", "Oregon", "af-south-1", "Cape Town", "ap-east-1", "Hong Kong");
        put(CITY_EN, "ap-east-2", "Taipei", "ap-south-1", "Mumbai", "ap-south-2", "Hyderabad", "ap-northeast-1", "Tokyo", "ap-northeast-2", "Seoul", "ap-northeast-3", "Osaka");
        put(CITY_EN, "ap-southeast-1", "Singapore", "ap-southeast-2", "Sydney", "ap-southeast-3", "Jakarta", "ap-southeast-4", "Melbourne", "ap-southeast-5", "Kuala Lumpur", "ap-southeast-6", "New Zealand");
        put(CITY_EN, "ap-southeast-7", "Bangkok", "ca-central-1", "Montreal", "ca-west-1", "Calgary", "eu-central-1", "Frankfurt", "eu-central-2", "Zurich", "eu-north-1", "Stockholm");
        put(CITY_EN, "eu-south-1", "Milan", "eu-south-2", "Spain", "eu-west-1", "Ireland", "eu-west-2", "London", "eu-west-3", "Paris", "il-central-1", "Tel Aviv");
        put(CITY_EN, "me-central-1", "UAE", "me-south-1", "Bahrain", "mx-central-1", "Mexico", "sa-east-1", "São Paulo", "cn-north-1", "Beijing", "cn-northwest-1", "Ningxia");
        put(CITY_EN, "us-gov-west-1", "GovCloud West", "us-gov-east-1", "GovCloud East", "ap-sydney-1", "Sydney", "ap-melbourne-1", "Melbourne", "sa-saopaulo-1", "São Paulo", "sa-vinhedo-1", "Vinhedo");
        put(CITY_EN, "ca-montreal-1", "Montreal", "ca-toronto-1", "Toronto", "sa-santiago-1", "Santiago", "sa-valparaiso-1", "Valparaíso", "sa-bogota-1", "Bogotá", "eu-paris-1", "Paris");
        put(CITY_EN, "eu-marseille-1", "Marseille", "eu-frankfurt-1", "Frankfurt", "ap-hyderabad-1", "Hyderabad", "ap-mumbai-1", "Mumbai", "ap-batam-1", "Batam", "il-jerusalem-1", "Jerusalem");
        put(CITY_EN, "eu-milan-1", "Milan", "eu-turin-1", "Turin", "ap-osaka-1", "Osaka", "ap-tokyo-1", "Tokyo", "ap-kulai-2", "Kulai", "mx-queretaro-1", "Querétaro");
        put(CITY_EN, "mx-monterrey-1", "Monterrey", "af-casablanca-1", "Casablanca", "eu-amsterdam-1", "Amsterdam", "me-riyadh-1", "Riyadh", "me-jeddah-1", "Jeddah", "eu-jovanovac-1", "Jovanovac");
        put(CITY_EN, "ap-singapore-1", "Singapore", "ap-singapore-2", "West Singapore", "af-johannesburg-1", "Johannesburg", "ap-seoul-1", "Seoul", "ap-chuncheon-1", "Chuncheon", "eu-madrid-1", "Madrid");
        put(CITY_EN, "eu-madrid-3", "Madrid 3", "eu-stockholm-1", "Stockholm", "eu-zurich-1", "Zurich", "me-abudhabi-1", "Abu Dhabi", "me-dubai-1", "Dubai", "uk-london-1", "London");
        put(CITY_EN, "uk-cardiff-1", "Newport", "us-ashburn-1", "Ashburn", "us-chicago-1", "Chicago", "us-phoenix-1", "Phoenix", "us-sanjose-1", "San Jose", "eastasia", "Hong Kong");
        put(CITY_EN, "southeastasia", "Singapore", "japaneast", "East Japan", "japanwest", "West Japan", "koreacentral", "Central Korea", "koreasouth", "South Korea", "australiaeast", "New South Wales");
        put(CITY_EN, "australiasoutheast", "Victoria", "australiacentral", "Canberra", "centralindia", "Pune", "southindia", "Chennai", "westindia", "Mumbai", "eastus", "Virginia");
        put(CITY_EN, "eastus2", "Virginia 2", "westus", "California", "westus2", "Washington", "westus3", "Arizona", "centralus", "Iowa", "northcentralus", "Illinois");
        put(CITY_EN, "southcentralus", "Texas", "westcentralus", "Wyoming", "canadacentral", "Toronto", "canadaeast", "Quebec", "brazilsouth", "São Paulo", "mexicocentral", "Querétaro");
        put(CITY_EN, "northeurope", "Ireland", "westeurope", "Netherlands", "uksouth", "London", "ukwest", "Cardiff", "francecentral", "Paris", "germanywestcentral", "Frankfurt");
        put(CITY_EN, "switzerlandnorth", "Zurich", "norwayeast", "Oslo", "swedencentral", "Gävle", "polandcentral", "Warsaw", "italynorth", "Milan", "spaincentral", "Madrid");
        put(CITY_EN, "uaenorth", "Dubai", "qatarcentral", "Doha", "israelcentral", "Israel", "southafricanorth", "Johannesburg", "indonesiacentral", "Jakarta", "malaysiawest", "Kuala Lumpur");
        put(CITY_EN, "newzealandnorth", "Auckland");
        put(OCI_KEY, "SYD", "ap-sydney-1", "MEL", "ap-melbourne-1", "GRU", "sa-saopaulo-1", "VCP", "sa-vinhedo-1", "YUL", "ca-montreal-1", "YYZ", "ca-toronto-1", "SCL", "sa-santiago-1", "VAP", "sa-valparaiso-1");
        put(OCI_KEY, "BOG", "sa-bogota-1", "CDG", "eu-paris-1", "MRS", "eu-marseille-1", "FRA", "eu-frankfurt-1", "HYD", "ap-hyderabad-1", "BOM", "ap-mumbai-1", "HSG", "ap-batam-1", "MTZ", "il-jerusalem-1");
        put(OCI_KEY, "LIN", "eu-milan-1", "NRQ", "eu-turin-1", "KIX", "ap-osaka-1", "NRT", "ap-tokyo-1", "JBP", "ap-kulai-2", "QRO", "mx-queretaro-1", "MTY", "mx-monterrey-1", "LEJ", "af-casablanca-1");
        put(OCI_KEY, "AMS", "eu-amsterdam-1", "RUH", "me-riyadh-1", "JED", "me-jeddah-1", "BEG", "eu-jovanovac-1", "SIN", "ap-singapore-1", "XSP", "ap-singapore-2", "JNB", "af-johannesburg-1", "ICN", "ap-seoul-1");
        put(OCI_KEY, "YNY", "ap-chuncheon-1", "MAD", "eu-madrid-1", "ORF", "eu-madrid-3", "ARN", "eu-stockholm-1", "ZRH", "eu-zurich-1", "AUH", "me-abudhabi-1", "DXB", "me-dubai-1", "LHR", "uk-london-1");
        put(OCI_KEY, "CWL", "uk-cardiff-1", "IAD", "us-ashburn-1", "ORD", "us-chicago-1", "PHX", "us-phoenix-1", "SJC", "us-sanjose-1");
    }

    private static final Pattern AWS_AZ = Pattern.compile("^([a-z]{2}(?:-[a-z]+)+-\\d+)[a-z]$");
    private static final Pattern OCI_AD = Pattern.compile("([a-z]+-[a-z]+-\\d+)-ad-\\d+$");
    private static final Pattern OCI_KEY_AD = Pattern.compile("(?:^|:)([A-Za-z]{3})-AD-\\d+$", Pattern.CASE_INSENSITIVE);

    /** 城市名；未知返回 ""。也识别 AWS 可用区 ap-northeast-1a、OCI AD AP-TOKYO-1-AD-1 / Uocm:NRT-AD-1。 */
    static String city(String code) {
        if (code == null) return "";
        String raw = code.trim(), c = raw.toLowerCase(Locale.ROOT);
        if (c.isEmpty() || "null".equals(c)) return "";
        String v = cityName(c);
        if (v != null) return v;
        Matcher m = AWS_AZ.matcher(c);
        if (m.find() && hasCity(m.group(1))) return cityName(m.group(1));
        m = OCI_AD.matcher(c);
        if (m.find() && hasCity(m.group(1))) return cityName(m.group(1));
        m = OCI_KEY_AD.matcher(raw);
        if (m.find()) { String r = OCI_KEY.get(m.group(1).toUpperCase(Locale.ROOT)); if (r != null && hasCity(r)) return cityName(r); }
        return "";
    }

    /** 「ap-northeast-1 · 东京」；未知只返回代码。 */
    static String label(String code) {
        if (code == null) return "";
        String c = city(code);
        return c.isEmpty() ? code : code + " · " + c;
    }

    static String[] labels(String[] codes) {
        String[] out = new String[codes.length];
        for (int i = 0; i < codes.length; i++) out[i] = label(codes[i]);
        return out;
    }

    /** 总览卡片（/accounts/{id}/overview 的 regions，已按台数降序）：1 个区域「ap-northeast-1 · 东京」，多个「东京 等 2 个区域」，没有返回 ""。与 core.js regionsBrief 相同。 */
    static String brief(org.json.JSONArray regions) {
        if (regions == null || regions.length() == 0) return "";
        String first = regions.optJSONObject(0).optString("region");
        if (regions.length() == 1) return label(first);
        String c = city(first);
        return (c.isEmpty() ? first : c) + (EN ? " and " + regions.length() + " more regions" : " 等 " + regions.length() + " 个区域");
    }

    /** 多区域分布「东京 2 · 新加坡 1」（城市名未知时用代码）。与 core.js regionsDist 相同。 */
    static String dist(org.json.JSONArray regions) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; regions != null && i < regions.length(); i++) {
            org.json.JSONObject r = regions.optJSONObject(i);
            String code = r.optString("region"), c = city(code);
            if (sb.length() > 0) sb.append(" · ");
            sb.append(c.isEmpty() ? code : c).append(' ').append(r.optInt("count"));
        }
        return sb.toString();
    }

    /** 实例数「3 台（运行 2）· EC2 2 · Lightsail 1」，与 core.js overviewCount 相同。 */
    static String count(org.json.JSONObject o) {
        java.util.List<String> parts = new java.util.ArrayList<>();
        if ("aws".equals(o.optString("provider"))) {
            int ls = o.optInt("lightsail");
            parts.add("EC2 " + o.optInt("ec2"));
            parts.add("Lightsail " + (o.optBoolean("lightsail_failed") ? (ls > 0 ? ls + (EN ? " (partial region failure)" : "（部分区域失败）") : (EN ? "Query failed" : "查询失败")) : String.valueOf(ls)));
        }
        org.json.JSONArray err = o.optJSONArray("errors");
        if (err != null && err.length() > 0) parts.add(EN ? err.length() + " region queries failed" : err.length() + " 个区域查询失败");
        return EN ? o.optInt("total") + " instances (" + o.optInt("running") + " running)" + (parts.isEmpty() ? "" : "· " + String.join(" · ", parts)) : o.optInt("total") + " 台（运行 " + o.optInt("running") + "）" + (parts.isEmpty() ? "" : "· " + String.join(" · ", parts));
    }

    // ---------------- build 25：有机器的区域（GET /accounts 的 machine_regions，台数多的在前；null = 还没扫描过，[] = 没有机器） ----------------

    /** 本次会话里 /overview 查到的结果（比 /accounts 带的记录新）；重新拉 /accounts 时清空。 */
    static final Map<Integer, org.json.JSONArray> HINTS = new java.util.concurrent.ConcurrentHashMap<>();
    /** 已经刷新过（或正在刷新）的账号，避免同一会话里重复排队。 */
    static final java.util.Set<Integer> REFRESHED = java.util.Collections.synchronizedSet(new java.util.HashSet<>());

    static org.json.JSONArray machineRegions(org.json.JSONObject acc) {
        org.json.JSONArray h = HINTS.get(acc.optInt("id"));
        if (h != null) return h;
        return acc.isNull("machine_regions") ? null : acc.optJSONArray("machine_regions");
    }

    /** 机器最多的区域；Azure 按订阅管理不用区域，没有记录 / 没有机器时返回 ""。与 core.js machineRegion 相同。 */
    static String machineRegion(org.json.JSONObject acc) {
        if ("azure".equals(acc.optString("provider"))) return "";
        org.json.JSONArray l = machineRegions(acc);
        return l == null || l.length() == 0 ? "" : l.optJSONObject(0).optString("region");
    }

    /** 当前区域：手动选过的 > 机器最多的区域 > 账号默认区域。 */
    static String current(org.json.JSONObject acc) {
        String p = Api.pref("region_" + acc.optInt("id"), "");
        if (!p.isEmpty()) return p;
        String m = machineRegion(acc);
        return m.isEmpty() ? BaseActivity.str(acc, "region", "") : m;
    }

    /** 账号列表的区域文字，与 core.js accountRegionText 相同：有机器「ap-northeast-1 · 东京」/「东京 等 2 个区域」；
     *  没有机器「无机器 · 默认 us-east-1 · 弗吉尼亚北部」；还没扫描过「us-east-1 · 弗吉尼亚北部（默认区域）」。 */
    static String accountText(org.json.JSONObject acc) {
        org.json.JSONArray l = machineRegions(acc);
        if (l != null && l.length() > 0) return brief(l);
        if ("azure".equals(acc.optString("provider"))) return l == null ? "" : (EN ? "No instances" : "无机器");
        String r = BaseActivity.str(acc, "region", "");
        String d = r.isEmpty() ? "-" : label(r);
        return l == null ? d + (EN ? " (default)" : "（默认区域）") : (EN ? "No instances · default " + d : "无机器 · 默认 " + d);
    }

    /** /overview 的结果记下来（列表与打开账号时的默认区域马上用上）。 */
    static void apply(int id, org.json.JSONObject o) {
        org.json.JSONArray rs = o == null ? null : o.optJSONArray("regions");
        if (rs == null) return;
        java.util.List<org.json.JSONObject> l = new java.util.ArrayList<>();
        for (int i = 0; i < rs.length(); i++) {
            org.json.JSONObject r = rs.optJSONObject(i);
            if (r == null || r.optInt("count") <= 0) continue;
            try { l.add(new org.json.JSONObject().put("region", r.optString("region")).put("count", r.optInt("count")).put("running", r.optInt("running"))); }
            catch (org.json.JSONException ignored) { }
        }
        l.sort((a, b) -> a.optInt("count") != b.optInt("count") ? b.optInt("count") - a.optInt("count")
                : a.optInt("running") != b.optInt("running") ? b.optInt("running") - a.optInt("running") : a.optString("region").compareTo(b.optString("region")));
        HINTS.put(id, new org.json.JSONArray(l));
    }

    /** 账号列表懒加载：没有记录 / 记录过期的账号逐个（一次一个，后台线程）查 /overview，每查完一个在主线程回调一次。 */
    static void refreshHints(android.app.Activity act, org.json.JSONArray accs, java.util.function.IntConsumer each) {
        java.util.List<Integer> todo = new java.util.ArrayList<>();
        for (int i = 0; accs != null && i < accs.length(); i++) {
            org.json.JSONObject a = accs.optJSONObject(i);
            int id = a.optInt("id");
            if (a.optInt("disabled") == 1 || HINTS.containsKey(id) || REFRESHED.contains(id)) continue;
            if (!a.isNull("machine_regions") && !a.optBoolean("machine_regions_stale")) continue;
            REFRESHED.add(id);
            todo.add(id);
        }
        if (todo.isEmpty()) return;
        new Thread(() -> {
            for (int id : todo) {
                try {
                    Object r = Api.call("GET", "/accounts/" + id + "/overview", null);
                    if (r instanceof org.json.JSONObject) apply(id, (org.json.JSONObject) r);
                    act.runOnUiThread(() -> { if (!act.isFinishing()) each.accept(id); });
                } catch (Exception ignored) { }
            }
        }, "tc-region-hints").start();
    }
}
