"""Auto-translate driver full names to Chinese. Used as fallback when DRIVER_CN misses."""

import re

FIRST_NAME_CN = {
    # English / European
    "alex": "亚历克斯", "alexander": "亚历山大", "alexandre": "亚历山大",
    "andrea": "安德里亚", "antonio": "安东尼奥", "arthur": "阿蒂尔",
    "arvid": "阿尔维德", "ayumu": "步梦", "brandon": "布兰登", "brendon": "布兰登",
    "callum": "卡勒姆", "carlos": "卡洛斯", "charles": "夏尔",
    "charlie": "查理", "christian": "克里斯蒂安", "cian": "西恩",
    "clement": "克莱芒", "daniel": "丹尼尔", "daniil": "丹尼尔",
    "david": "大卫", "dennis": "丹尼斯", "dino": "迪诺",
    "enzo": "恩佐", "esteban": "埃斯特班", "estebanon": "埃斯特班",
    "felipe": "菲利佩", "fernando": "费尔南多", "franco": "弗兰科",
    "frederik": "弗雷德里克", "fred": "弗雷德", "gabriel": "加布里埃尔",
    "george": "乔治", "giuseppe": "朱塞佩", "guanyu": "冠宇",
    "harry": "哈里", "hugh": "休", "isack": "伊萨克",
    "jack": "杰克", "jake": "杰克", "jak": "杰克",
    "james": "詹姆斯", "jenson": "詹森", "jimmy": "吉米",
    "john": "约翰", "jonathan": "乔纳森", "juan": "胡安",
    "julian": "朱利安", "kevin": "凯文", "kimi": "基米",
    "lance": "兰斯", "lando": "兰多", "lewis": "刘易斯",
    "liam": "利亚姆", "logan": "洛根", "luke": "卢克",
    "marcus": "马库斯", "mark": "马克", "max": "马克斯",
    "michael": "迈克尔", "mick": "米克", "mika": "米卡",
    "nate": "内特", "nicholas": "尼古拉斯", "nick": "尼克",
    "nico": "尼科", "nikita": "尼基塔", "nyck": "尼克",
    "oliver": "奥利弗", "ollie": "奥利", "oscar": "奥斯卡",
    "patrick": "帕特里克", "patricio": "帕特里西奥",
    "paul": "保罗", "peter": "彼得", "pierre": "皮埃尔",
    "pietro": "皮埃特罗", "rafael": "拉斐尔",
    "richard": "理查德", "robert": "罗伯特",
    "romain": "罗曼", "ryo": "亮",
    "sam": "山姆", "scott": "斯科特",
    "sebastian": "塞巴斯蒂安", "sergio": "塞尔吉奥",
    "simon": "西蒙", "sofia": "索菲亚", "stephen": "斯蒂芬",
    "steven": "史蒂文", "stoffel": "斯托菲尔",
    "takumi": "匠", "taro": "太郎", "theo": "西奥", "thomas": "托马斯",
    "tim": "蒂姆", "tom": "汤姆", "valtteri": "瓦尔特利",
    "victor": "维克多", "vincent": "文森特",
    "william": "威廉", "yuki": "裕毅",
    "zak": "扎克", "zane": "赞恩",
}

LAST_NAME_CN = {
    "abbi": "阿比", "aitken": "艾特肯", "albon": "阿尔本",
    "alonso": "阿隆索", "antonelli": "安东内利", "aron": "阿龙",
    "badoer": "巴多尔", "barnard": "巴纳德", "bearman": "比尔曼",
    "beganovic": "贝加诺维奇",     "bonito": "博尼托",
    "bortoleto": "博托莱托", "bottas": "博塔斯",
    "brown": "布朗", "browning": "布朗宁", "brundle": "布伦德尔",
    "camara": "卡马拉", "campos": "坎波斯",
    "carr": "卡尔", "colapinto": "科拉平托",
    "cordeel": "科迪尔", "cowell": "考威尔",
    "crawford": "克劳福德", "darling": "达林",
    "de vries": "德弗里斯", "deledda": "德莱达",
    "doohan": "杜汉", "drugovich": "德鲁戈维奇",
    "dunne": "邓恩", "dürksen": "杜克森",
    "egan": "伊根", "eriksson": "埃里克森",
    "fittipaldi": "菲蒂帕尔迪", "foster": "福斯特",
    "fuoco": "福科", "gasly": "加斯利",
    "giovinazzi": "吉奥维纳兹",
    "goethe": "歌德", "gray": "格雷",
    "grosjean": "格罗斯让", "günther": "冈瑟",
    "haas": "哈斯", "hadjar": "哈贾尔",
    "hamilton": "汉密尔顿", "hartley": "哈特利",
    "hauger": "豪格", "hirakawa": "平川",
    "hughes": "休斯", "hulkenberg": "霍肯伯格",
    "iwasa": "岩佐", "jackson": "杰克逊",
    "johnson": "约翰逊", "jones": "琼斯",
    "kennedy": "肯尼迪", "kim": "金",
    "kubica": "库比卡", "kvyat": "科维亚特",
    "latifi": "拉提菲", "lawson": "劳森",
    "leclerc": "勒克莱尔", "lee": "李",
    "lindblad": "林德布拉德", "lynn": "林恩",
    "magnussen": "马格努森", "maldonado": "马尔多纳多",
    "mansell": "曼塞尔", "marquez": "马奎兹",
    "martins": "马丁斯", "mazepin": "马泽平",
    "mccarthy": "麦卡锡", "mclaren": "迈凯伦",
    "miyata": "宫田", "montoya": "蒙托亚",
    "morgan": "摩根", "murray": "穆雷",
    "nakamura": "中村", "nato": "纳托",
    "nelson": "纳尔逊", "norris": "诺里斯",
    "o'connor": "奥康纳", "o'ward": "奥沃德", "o'neill": "奥尼尔",
    "ocon": "奥康", "owen": "欧文",
    "palmer": "帕尔默", "perez": "佩雷兹",
    "piastri": "皮亚斯特里", "pourchaire": "波谢尔",
    "pull": "普尔", "quinn": "奎因",
    "raikkonen": "莱科宁", "ricciardo": "里卡多",
    "robinson": "罗宾逊", "russell": "拉塞尔",
    "sainz": "赛恩斯", "sargeant": "萨金特",
    "sato": "佐藤", "schumacher": "舒马赫",
    "schwartzman": "施瓦茨曼", "shwartzman": "施瓦茨曼", "senna": "塞纳",
    "shields": "希尔兹", "sirotkin": "斯洛特金",
    "slater": "斯莱特", "smith": "史密斯",
    "stroll": "斯特罗尔", "sullivan": "沙利文",
    "tai": "戴", "takahashi": "高桥",
    "tanaka": "田中", "taylor": "泰勒",
    "thompson": "汤普森", "tsunoda": "角田",
    "upton": "厄普顿", "vandoorne": "范多恩",
    "verstappen": "维斯塔潘", "vesti": "维斯蒂",
    "villeneuve": "维伦纽夫", "vips": "维普斯",
    "walker": "沃克", "wallace": "华莱士",
    "watson": "沃森", "weber": "韦伯",
    "weiss": "魏斯", "white": "怀特",
    "wilson": "威尔逊", "wong": "黄",
    "yamamoto": "山本", "yamashita": "山下",
    "young": "杨", "zhou": "周",
    "zhu": "朱",
}


def _clean_name(name):
    if not name:
        return ""
    return re.sub(r"[^a-z\s\-'\.]", "", str(name).lower()).strip()


def auto_cn_short(code, full_name):
    code_str = str(code).upper()
    name = _clean_name(full_name)
    if not name:
        return code_str
    parts = name.split()
    last = parts[-1] if parts else ""
    cn_last = LAST_NAME_CN.get(last, last.capitalize())
    return f"{code_str} {cn_last}"


def auto_cn_full(code, full_name):
    code_str = str(code).upper()
    name = _clean_name(full_name)
    if not name:
        return code_str
    parts = name.split()
    first_cn_parts = []
    for p in parts[:-1]:
        first_cn_parts.append(FIRST_NAME_CN.get(p, p.capitalize()))
    last = parts[-1] if parts else ""
    last_cn = LAST_NAME_CN.get(last, last.capitalize())
    if first_cn_parts:
        return "·".join(first_cn_parts) + "·" + last_cn
    return last_cn
