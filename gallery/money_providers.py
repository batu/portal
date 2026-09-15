"""Read-only Meta, Google Ads, and AdMob adapters for the Money page."""

import json
import re
import stat
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from contextvars import ContextVar
from datetime import date

from .money import amount

STORE_GAMES = {"6796698146": "find-the-bird", "6772100729": "find-the-dog",
               "com.basegamelab.findthebird": "find-the-bird", "com.baseardahan.hiddenobj": "find-the-dog"}
META_GAMES = {"1327770709435424": "find-the-bird", "1853281595338180": "find-the-dog"}
_deadline = ContextVar("money_provider_deadline", default=None)


def secret(path):
    file = Path(path).expanduser()
    info = file.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Reporting credentials must be owner-only regular files")
    value = file.read_text().strip()
    if not value or any(c.isspace() for c in value):
        raise ValueError("Invalid reporting credential")
    return value


def request_json(url, token, body=None, headers=None, *, form=False):
    remaining = _deadline.get() - time.monotonic() if _deadline.get() else 25
    if remaining <= 0:
        raise TimeoutError("Provider reporting deadline reached")
    payload = urllib.parse.urlencode(body) if form else json.dumps(body)
    req = urllib.request.Request(url, data=payload.encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/x-www-form-urlencoded" if form else "application/json",
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=min(25, remaining)) as response:
        raw = response.read(16_000_001)
    if len(raw) > 16_000_000:
        raise ValueError("Report exceeds size limit")
    return json.loads(raw)


def oauth(settings, scope):
    # Never start an interactive consent flow from a web request.
    cache = Path(settings["oauth_cache"]).expanduser()
    entries = json.loads(cache.read_text())
    credentials = json.loads(Path(settings["oauth_credentials"]).expanduser().read_text())["installed"]
    def matches(key):
        saved = json.loads(key)
        identity = json.loads(saved["CredentialsJSON"]).get("installed", {})
        # oauth2l normalizes redirect_uris before keying its cache.
        return (saved.get("Scope") == scope.replace(",", " ")
                and all(identity.get(field) == credentials.get(field) for field in ("client_id", "client_secret")))
    if not any(matches(k) for k in entries):
        raise ValueError("No existing OAuth grant for reporting")
    result = subprocess.run([settings.get("oauth2l", "oauth2l"), "fetch",
                             "--credentials=" + str(Path(settings["oauth_credentials"]).expanduser()),
                             "--cache=" + str(cache), "--scope=" + scope, "--refresh",
                             "--disableAutoOpenConsentPage", "--consentPageInteractionTimeout=1",
                             "--consentPageInteractionTimeoutUnits=seconds"], capture_output=True, text=True, timeout=20)
    token = result.stdout.strip()
    if result.returncode or not token.startswith("ya29.") or any(c.isspace() for c in token):
        raise ValueError("Reporting authorization unavailable")
    return token


def meta(settings, start, end):
    token = secret(settings["token_file"])
    account = settings["account_id"]
    if not re.fullmatch(r"\d+", account):
        raise ValueError("Invalid Meta account")
    root = f"https://graph.facebook.com/v23.0/act_{account}"
    info = request_json(root + "?fields=currency,timezone_name", token)
    if info["currency"] != "TRY" or info["timezone_name"] not in {"Turkey", "Europe/Istanbul"}:
        raise ValueError("Incompatible Meta currency/time zone")
    params = {"fields": "ad_id,ad_name,adset_id,spend,actions", "level": "ad",
              "time_range": json.dumps({"since": start, "until": end}), "limit": "500",
              "action_report_time": "impression", "action_attribution_windows": '["7d_click","1d_view"]'}
    rows, identities, cursors = [], {}, set()
    for _ in range(20):
        data = request_json(root + "/insights?" + urllib.parse.urlencode(params), token)
        unresolved = sorted({row["adset_id"] for row in data["data"]} - identities.keys())
        if any(not re.fullmatch(r"\d+", adset) for adset in unresolved):
            raise ValueError("Invalid adset")
        for offset in range(0, len(unresolved), 50):
            batch = unresolved[offset:offset + 50]
            queries = [{"method": "GET", "relative_url": f"{adset}?fields=promoted_object"} for adset in batch]
            objects = request_json("https://graph.facebook.com/v23.0/", token,
                                   {"batch": json.dumps(queries)}, form=True)
            if len(objects) != len(batch):
                raise ValueError("Incomplete Meta identity batch")
            for adset, result in zip(batch, objects):
                if result["code"] != 200:
                    raise ValueError("Meta identity unavailable")
                promoted = json.loads(result["body"]).get("promoted_object", {})
                identities[adset] = META_GAMES.get(promoted.get("application_id"))
                if not promoted.get("application_id"):
                    raise ValueError("Cannot resolve ad game identity")
        for row in data["data"]:
            adset = row["adset_id"]
            game = identities[adset]
            if game:
                # omni_app_install overlaps mobile_app_install; never add both.
                values = [v["value"] for v in row.get("actions", [])
                          if v["action_type"] == "mobile_app_install"]
                installs = str(sum((amount(v) for v in values), amount(0)))
                rows.append({"game": game, "ad_id": row["ad_id"], "name": row["ad_name"],
                             "spend": str(amount(row["spend"])), "installs": installs})
        paging = data.get("paging", {})
        if not paging.get("next"):
            return {"currency": "TRY", "timezone": "Europe/Istanbul", "rows": rows}
        cursor = paging["cursors"]["after"]
        if cursor in cursors:
            raise ValueError("Repeated report cursor")
        cursors.add(cursor)
        params["after"] = cursor
    raise ValueError("Incomplete Meta pagination")


def google_ads(settings, start, end):
    token = oauth(settings, "https://www.googleapis.com/auth/adwords")
    headers = {"developer-token": secret(settings["developer_token_file"])}
    if settings.get("login_customer_id"):
        headers["login-customer-id"] = settings["login_customer_id"]
    rows = []
    customers = settings["customer_ids"]
    if not customers or len(customers) != len(set(customers)):
        raise ValueError("Provide unique Google Ads customers")
    for customer in customers:
        if not re.fullmatch(r"\d+", customer):
            raise ValueError("Invalid customer")
        url = f"https://googleads.googleapis.com/v23/customers/{customer}/googleAds:search"
        info = request_json(url, token, {"query": "SELECT customer.currency_code, customer.time_zone, customer.manager FROM customer"}, headers)
        account = info["results"][0]["customer"]
        if account["currencyCode"] != "TRY" or account["timeZone"] != "Europe/Istanbul" or account.get("manager"):
            raise ValueError("Incompatible Google Ads account")
        def search(query):
            body = {"query": query}
            for _ in range(20):
                data = request_json(url, token, body, headers)
                yield from data.get("results", [])
                if not data.get("nextPageToken"):
                    return
                body["pageToken"] = data["nextPageToken"]
            raise ValueError("Incomplete Google Ads pagination")

        window = f"segments.date BETWEEN '{start}' AND '{end}'"
        campaigns = {}
        for row in search("SELECT campaign.id, campaign.name, campaign.app_campaign_setting.app_id, metrics.cost_micros "
                          f"FROM campaign WHERE {window} AND metrics.cost_micros > 0"):
            campaign = row["campaign"]
            app_id = campaign.get("appCampaignSetting", {}).get("appId")
            if not app_id:
                raise ValueError("Cannot resolve campaign app identity")
            game = STORE_GAMES.get(app_id)
            if game:
                campaigns[campaign["id"]] = {"game": game, "name": campaign["name"],
                                              "micros": amount(row["metrics"]["costMicros"])}
        if not campaigns:
            continue
        if any(not re.fullmatch(r"\d+", key) for key in campaigns):
            raise ValueError("Invalid campaign identity")
        campaign_filter = "campaign.id IN (" + ",".join(campaigns) + ")"
        ads = search("SELECT campaign.id, ad_group_ad.resource_name, ad_group_ad.ad.id, ad_group_ad.ad.name, metrics.cost_micros "
                     f"FROM ad_group_ad WHERE {window} AND {campaign_filter} AND metrics.cost_micros > 0")
        conversions = search("SELECT ad_group_ad.resource_name, segments.conversion_action_category, metrics.conversions "
                             f"FROM ad_group_ad WHERE {window} AND {campaign_filter} AND segments.conversion_action_category = 'DOWNLOAD'")
        installs = {}
        for row in conversions:
            identity = row["adGroupAd"]["resourceName"]
            installs[identity] = installs.get(identity, amount(0)) + amount(row["metrics"].get("conversions", "0"))
        seen_cost = {identity: amount(0) for identity in campaigns}
        for row in ads:
            campaign_id = row["campaign"]["id"]
            if campaign_id not in campaigns:
                continue
            campaign = campaigns[campaign_id]
            identity = row["adGroupAd"]["resourceName"]
            ad = row["adGroupAd"]["ad"]
            micros = amount(row["metrics"]["costMicros"])
            seen_cost[campaign_id] += micros
            rows.append({"game": campaign["game"], "ad_id": identity,
                         "name": ad.get("name") or f'{campaign["name"]} · ad {ad["id"]}',
                         "spend": str(micros / 1_000_000), "installs": str(installs.get(identity, amount(0)))})
        if any(seen_cost[key] != value["micros"] for key, value in campaigns.items()):
            raise ValueError("Google ad spend does not reconcile to campaign totals")
    return {"currency": "TRY", "timezone": "Europe/Istanbul", "rows": rows}


def admob(settings, start, end):
    token = oauth(settings, "https://www.googleapis.com/auth/admob.readonly,https://www.googleapis.com/auth/admob.report,https://www.googleapis.com/auth/admob.monetization")
    publisher = settings["publisher_id"]
    if not re.fullmatch(r"pub-\d+", publisher):
        raise ValueError("Invalid publisher")
    root = f"https://admob.googleapis.com/v1/accounts/{publisher}"
    accounts = request_json("https://admob.googleapis.com/v1/accounts", token)
    account = next(a for a in accounts["account"] if a["publisherId"] == publisher)
    if account["reportingTimeZone"] != "Europe/Istanbul":
        raise ValueError("Incompatible AdMob time zone")
    apps, params = {}, {"pageSize": "100"}
    for _ in range(20):
        page = request_json(root + "/apps?" + urllib.parse.urlencode(params), token)
        for app in page.get("apps", []):
            game = STORE_GAMES.get(app.get("linkedAppInfo", {}).get("appStoreId"))
            # Unlinked app identities may be explicitly mapped by the operator.
            game = game or settings.get("app_games", {}).get(app["appId"])
            if game:
                apps[app["appId"]] = game
        if not page.get("nextPageToken"):
            break
        params["pageToken"] = page["nextPageToken"]
    else:
        raise ValueError("Incomplete AdMob apps")
    if set(apps.values()) != {"find-the-bird", "find-the-dog"}:
        raise ValueError("Missing game AdMob identities")
    def parts(value):
        parsed = date.fromisoformat(value)
        return {"year": parsed.year, "month": parsed.month, "day": parsed.day}
    body = {"reportSpec": {"dateRange": {"startDate": parts(start), "endDate": parts(end)},
                           "dimensions": ["APP"], "metrics": ["ESTIMATED_EARNINGS"],
                           "localizationSettings": {"currencyCode": "TRY"}, "maxReportRows": 100000}}
    data = request_json(root + "/mediationReport:generate", token, body)
    if not any("footer" in item for item in data) or any(item.get("footer", {}).get("warnings") for item in data):
        raise ValueError("Incomplete AdMob report")
    footer = next(item["footer"] for item in data if "footer" in item)
    if int(footer.get("matchingRowCount", 0)) != sum("row" in item for item in data):
        raise ValueError("Truncated AdMob report")
    header = next(item["header"] for item in data if "header" in item)
    if header["localizationSettings"]["currencyCode"] != "TRY":
        raise ValueError("Unexpected AdMob currency")
    rows = []
    for item in data:
        if "row" not in item:
            continue
        row = item["row"]
        game = apps.get(row["dimensionValues"]["APP"]["value"])
        if game:
            rows.append({"game": game, "revenue": str(amount(row["metricValues"]["ESTIMATED_EARNINGS"]["microsValue"]) / 1_000_000)})
    return {"currency": "TRY", "timezone": "Europe/Istanbul", "rows": rows}


def fetch_report(provider, settings, start, end):
    deadline = _deadline.set(time.monotonic() + 60)
    try:
        return {"meta": meta, "google_ads": google_ads, "admob": admob}[provider](settings, start, end)
    finally:
        _deadline.reset(deadline)
