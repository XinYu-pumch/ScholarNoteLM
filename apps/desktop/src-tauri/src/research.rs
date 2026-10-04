#[path = "zotero_import.rs"]
mod zotero_import;
pub use zotero_import::worker_entry as zotero_worker_entry;
#[allow(unused_imports)] // Foreground waiting is exposed only by research-cli.
pub use zotero_import::wait_for_job as wait_for_zotero_job;
use base64::Engine;
use calamine::{open_workbook_auto, Reader};
use fs2::FileExt;
use reqwest::blocking::Client;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{HashMap, HashSet},
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    path::Path,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

pub type R<T> = Result<T, String>;
fn err(e: impl std::fmt::Display) -> String {
    e.to_string()
}
fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn uid() -> String {
    format!(
        "{}-{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos(),
        std::process::id()
    )
}
fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn valid_id(id: &str) -> R<()> {
    if id.is_empty()
        || id.len() > 100
        || !id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        Err("无效的项目或检索式标识".into())
    } else {
        Ok(())
    }
}
fn client(seconds: u64) -> R<Client> {
    Client::builder()
        .timeout(Duration::from_secs(seconds))
        .connect_timeout(Duration::from_secs(25))
        .user_agent("ScholarNoteLM/0.2 (literature research)")
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(err)
}
fn model_client(seconds: u64) -> R<Client> {
    Client::builder().no_proxy()
        .timeout(Duration::from_secs(seconds))
        .connect_timeout(Duration::from_secs(25))
        .user_agent("ScholarNoteLM/0.2 (literature research)")
        .redirect(reqwest::redirect::Policy::none())
        .build().map_err(err)
}
fn write_file(path: &Path, bytes: &[u8]) -> R<()> {
    fs::create_dir_all(path.parent().unwrap()).map_err(err)?;
    let tmp = path.with_extension(format!("{}.tmp", uid()));
    let mut f = File::create(&tmp).map_err(err)?;
    f.write_all(bytes).map_err(err)?;
    f.sync_all().map_err(err)?;
    fs::rename(tmp, path).map_err(err)
}
fn db(root: &Path) -> R<Connection> { db_at(root, None) }
fn db_project(root: &Path, project: &str) -> R<Connection> { db_at(root, Some(project)) }
fn db_at(root: &Path, project: Option<&str>) -> R<Connection> {
    fs::create_dir_all(root.join("data/research")).map_err(err)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(
            root.join("data/research"),
            fs::Permissions::from_mode(0o700),
        )
        .map_err(err)?;
    }
    let path = if let Some(p) = project { project_dir(root,p)?.join("metadata/research.sqlite3") } else { root.join("data/research/research.sqlite3") };
    fs::create_dir_all(path.parent().unwrap()).map_err(err)?;
    let c = Connection::open(path).map_err(err)?;
    c.busy_timeout(Duration::from_secs(15)).map_err(err)?;
    c.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
      CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS queries(id TEXT PRIMARY KEY, project TEXT NOT NULL, name TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1, archived INTEGER NOT NULL DEFAULT 0, active_run TEXT, last_error TEXT NOT NULL DEFAULT '');
      CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, query_id TEXT NOT NULL, revision INTEGER NOT NULL, created INTEGER NOT NULL, data TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS articles(pmid TEXT PRIMARY KEY, data TEXT NOT NULL, xml TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS members(run_id TEXT NOT NULL, pmid TEXT NOT NULL, position INTEGER NOT NULL, data TEXT NOT NULL, xml TEXT NOT NULL, PRIMARY KEY(run_id,pmid));
      CREATE TABLE IF NOT EXISTS corpora(id TEXT PRIMARY KEY, project TEXT NOT NULL, created INTEGER NOT NULL, signature TEXT NOT NULL, manifest TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS query_project ON queries(project);
      CREATE INDEX IF NOT EXISTS corpus_project ON corpora(project,created);
      CREATE TABLE IF NOT EXISTS chat_threads(id TEXT PRIMARY KEY, project TEXT NOT NULL, name TEXT NOT NULL, parent_id TEXT, data TEXT NOT NULL, created INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0);").map_err(err)?;
    // One-time per-query migration preserves the previous project defaults.
    c.execute("INSERT OR IGNORE INTO settings(key,value) SELECT 'queryFilters:' || q.id, COALESCE((SELECT value FROM settings WHERE key='filters:' || q.project), ?) FROM queries q", [json!({"start":"","end":"","sort":"relevance","mode":"explore","limit":100,"jcr":false,"quartiles":["Q1","Q2"],"unknown":"exclude"}).to_string()]).map_err(err)?;
    if project.is_some() {
        drop(db(root)?);
        c.execute("ATTACH DATABASE ? AS system", [root.join("data/research/research.sqlite3").to_string_lossy().to_string()]).map_err(err)?;
    }
    Ok(c)
}
fn settings_table(c: &Connection, key: &str) -> &'static str {
    if !key.starts_with("queryFilters:") && !key.starts_with("filters:") && c.prepare("SELECT 1 FROM system.settings LIMIT 1").is_ok() { "system.settings" } else { "settings" }
}
fn setting(c: &Connection, key: &str, default: Value) -> R<Value> {
    let val: Option<String> = c
        .query_row(&format!("SELECT value FROM {} WHERE key=?", settings_table(c,key)), [key], |r| {
            r.get(0)
        })
        .optional()
        .map_err(err)?;
    Ok(val
        .and_then(|v| serde_json::from_str(&v).ok())
        .unwrap_or(default))
}
fn put(c: &Connection, key: &str, value: &Value) -> R<()> {
    c.execute(
        &format!("INSERT INTO {} VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",settings_table(c,key)),
        params![key, value.to_string()],
    )
    .map_err(err)?;
    Ok(())
}
fn defaults() -> Value {
    json!({"start":"","end":"","sort":"relevance","mode":"explore","limit":30,"jcr":false,"quartiles":[],"unknown":"keep"})
}
fn query_filters(c: &Connection, id: &str) -> R<Value> {
    setting(c, &format!("queryFilters:{id}"), defaults())
}
fn validate_filters(v: &Value) -> R<()> {
    for k in ["start", "end"] {
        if !s(v, k).is_empty() && chrono::NaiveDate::parse_from_str(s(v, k), "%Y-%m-%d").is_err() {
            return Err("日期须为 YYYY-MM-DD".into());
        }
    }
    if !s(v, "start").is_empty() && !s(v, "end").is_empty() && s(v, "start") > s(v, "end") {
        return Err("开始日期不能晚于结束日期".into());
    }
    if !["relevance", "pub_date"].contains(&s(v, "sort"))
        || !["explore", "full"].contains(&s(v, "mode"))
    {
        return Err("无效的检索模式".into());
    }
    if v["limit"]
        .as_u64()
        .filter(|n| *n >= 1 && *n <= 10000)
        .is_none()
    {
        return Err("探索数量应为 1–10000".into());
    }
    if v["jcr"] == true
        && v["quartiles"].as_array().map_or(true, |a| {
            a.is_empty()
                || a.iter()
                    .any(|q| !["Q1", "Q2", "Q3", "Q4"].contains(&q.as_str().unwrap_or("")))
        })
    {
        return Err("请选择有效的 JCR 分区".into());
    }
    Ok(())
}
fn norm(v: &str) -> String {
    v.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}
const COLS: [&str; 8] = [
    "Journal",
    "ISSN",
    "eISSN",
    "Category",
    "Total citation",
    "JIF",
    "Quartile",
    "JIF rank",
];
pub fn jcr_validate(path: &Path) -> R<Value> {
    let ext = path
        .extension()
        .and_then(|x| x.to_str())
        .unwrap_or("")
        .to_lowercase();
    if ext != "xlsx" && ext != "xls" {
        return Err("JCR 文件必须是 .xlsx 或 .xls".into());
    }
    let mut book = open_workbook_auto(path).map_err(|e| format!("无法读取 Excel：{e}"))?;
    let sheet = book
        .worksheet_range_at(0)
        .ok_or("工作簿没有工作表")?
        .map_err(err)?;
    let mut rows = sheet.rows();
    let header = rows.next().ok_or("工作表为空")?;
    let names: Vec<String> = header
        .iter()
        .map(|v| v.to_string().trim().to_string())
        .collect();
    let missing: Vec<_> = COLS
        .iter()
        .filter(|n| !names.iter().any(|v| v == **n))
        .collect();
    if !missing.is_empty() {
        return Err(format!(
            "缺少必需列：{}",
            missing.iter().map(|x| **x).collect::<Vec<_>>().join(", ")
        ));
    }
    let indices: Vec<_> = COLS
        .iter()
        .map(|n| names.iter().position(|x| x == n).unwrap())
        .collect();
    let mut records = Vec::new();
    let mut warnings = Vec::new();
    let mut invalid = Vec::new();
    for (i, row) in rows.enumerate() {
        let vals: Vec<String> = indices
            .iter()
            .map(|n| {
                row.get(*n)
                    .map(|x| x.to_string().trim().to_string())
                    .unwrap_or_default()
            })
            .collect();
        if vals.iter().all(|v| v.is_empty()) {
            continue;
        }
        let raw_q = vals[6].to_uppercase();
        // pandas.read_excel in BADR treats these spreadsheet NA markers as missing.
        let q = if ["N/A", "NA", "NAN", "NULL", "NONE", "#N/A", "#NA", "<NA>"]
            .contains(&raw_q.as_str())
        {
            String::new()
        } else {
            raw_q
        };
        if !q.is_empty() && !["Q1", "Q2", "Q3", "Q4"].contains(&q.as_str()) {
            invalid.push(format!("第 {} 行：{}", i + 2, q));
        }
        if vals[0].is_empty() {
            invalid.push(format!("第 {} 行：Journal 为空", i + 2));
        }
        if q.is_empty() {
            warnings.push(format!("第 {} 行未提供分区", i + 2));
        }
        records.push(json!({"journal":vals[0],"issn":vals[1],"eissn":vals[2],"category":vals[3],"citations":vals[4],"jif":vals[5],"quartile":q,"rank":vals[7]}));
    }
    if !invalid.is_empty() {
        return Err(format!(
            "JCR 校验未通过：{}",
            invalid.into_iter().take(12).collect::<Vec<_>>().join("；")
        ));
    }
    if records.is_empty() {
        return Err("JCR 文件没有数据行".into());
    }
    let count = records.len();
    let warning_count = warnings.len();
    Ok(
        json!({"rows":count,"columns":COLS,"records":records,"warningCount":warning_count,"warnings":warnings.into_iter().take(8).collect::<Vec<_>>()}),
    )
}
fn activate_jcr(root: &Path, c: &Connection, path: &Path, name: &str) -> R<Value> {
    let mut report = jcr_validate(path)?;
    let bytes = fs::read(path).map_err(err)?;
    let digest = hash(&bytes);
    let target = root.join(format!(
        "data/reference/jcr/{}.{}",
        digest,
        path.extension().unwrap().to_string_lossy()
    ));
    if !target.exists() {
        write_file(&target, &bytes)?
    }
    let records = report.as_object_mut().unwrap().remove("records").unwrap();
    write_file(
        &root.join(format!("data/reference/jcr/{digest}.json")),
        records.to_string().as_bytes(),
    )?;
    report["version"] = json!(digest);
    report["name"] = json!(name);
    report["activated"] = json!(now());
    put(c, "jcr", &report)?;
    Ok(report)
}
fn ensure_jcr(root: &Path, c: &Connection) -> R<Value> {
    let j = setting(c, "jcr", Value::Null)?;
    if j.is_null() {
        let p = root.join("data/reference/jcr/default-2025.xlsx");
        if p.exists() {
            activate_jcr(root, c, &p, "BADR · 2025JCR.xlsx")
        } else {
            Ok(Value::Null)
        }
    } else {
        Ok(j)
    }
}
struct Jcr {
    rows: Vec<Value>,
    by_issn: HashMap<String, Vec<usize>>,
    by_title: HashMap<String, Vec<usize>>,
}
impl Jcr {
    fn load(root: &Path, version: &str) -> R<Self> {
        let rows: Vec<Value> = serde_json::from_slice(
            &fs::read(root.join(format!("data/reference/jcr/{version}.json"))).map_err(err)?,
        )
        .map_err(err)?;
        let mut by_issn: HashMap<String, Vec<usize>> = HashMap::new();
        let mut by_title: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, r) in rows.iter().enumerate() {
            for k in ["issn", "eissn"] {
                let n = norm(s(r, k));
                if !n.is_empty() {
                    by_issn.entry(n).or_default().push(i);
                }
            }
            by_title.entry(norm(s(r, "journal"))).or_default().push(i);
        }
        Ok(Self {
            rows,
            by_issn,
            by_title,
        })
    }
    fn matched(&self, p: &Value) -> Vec<Value> {
        let mut ids = HashSet::new();
        if let Some(a) = p["issns"].as_array() {
            for v in a {
                if let Some(found) = self.by_issn.get(&norm(v.as_str().unwrap_or(""))) {
                    ids.extend(found.iter().copied());
                }
            }
        }
        if ids.is_empty() {
            if let Some(found) = self.by_title.get(&norm(s(p, "journal"))) {
                let identities: HashSet<_> = found
                    .iter()
                    .map(|i| {
                        (
                            norm(s(&self.rows[*i], "issn")),
                            norm(s(&self.rows[*i], "eissn")),
                        )
                    })
                    .collect();
                if identities.len() == 1 {
                    ids.extend(found.iter().copied());
                }
            }
        }
        let mut ids: Vec<_> = ids.into_iter().collect();
        ids.sort_unstable();
        ids.into_iter().map(|i| self.rows[i].clone()).collect()
    }
}
fn text(n: roxmltree::Node) -> String {
    n.descendants()
        .filter(|x| x.is_text())
        .filter_map(|x| x.text())
        .collect::<String>()
        .trim()
        .to_string()
}
fn child<'a, 'b>(n: roxmltree::Node<'a, 'b>, name: &str) -> Option<roxmltree::Node<'a, 'b>> {
    n.children().find(|x| x.has_tag_name(name))
}
fn val(n: roxmltree::Node, name: &str) -> String {
    child(n, name).map(text).unwrap_or_default()
}
pub fn parse_pubmed(xml: &str) -> R<Vec<(String, Value, String)>> {
    let doc = roxmltree::Document::parse_with_options(
        xml,
        roxmltree::ParsingOptions {
            allow_dtd: true,
            ..Default::default()
        },
    )
    .map_err(err)?;
    if !doc.root_element().has_tag_name("PubmedArticleSet") {
        return Err("需要 PubmedArticleSet 格式的 XML".into());
    }
    let mut out = Vec::new();
    let mut seen = HashSet::new();
    for node in doc
        .root_element()
        .children()
        .filter(|n| n.has_tag_name("PubmedArticle") || n.has_tag_name("PubmedBookArticle"))
    {
        let is_book = node.has_tag_name("PubmedBookArticle");
        let citation = child(node, if is_book { "BookDocument" } else { "MedlineCitation" })
            .ok_or("缺少 PubMed 文献主体")?;
        let pmid = val(citation, "PMID");
        if pmid.is_empty() || !pmid.chars().all(|c| c.is_ascii_digit()) {
            return Err("文献缺少有效的 PMID，未导入".into());
        }
        if !seen.insert(pmid.clone()) {
            continue;
        }
        let article = if is_book { citation } else { child(citation, "Article").ok_or("缺少 Article")? };
        let book = child(article, "Book");
        let journal = child(article, "Journal");
        let mut authors = Vec::new();
        if let Some(list) = child(article, "AuthorList") {
            for a in list.children().filter(|n| n.has_tag_name("Author")) {
                let name = format!("{} {}", val(a, "LastName"), val(a, "Initials"));
                authors.push(if name.trim().is_empty() {
                    val(a, "CollectiveName")
                } else {
                    name
                });
            }
        }
        let mut issns = Vec::new();
        if let Some(j) = journal {
            for i in j.children().filter(|n| n.has_tag_name("ISSN")) {
                issns.push(text(i));
            }
        }
        if let Some(info) = child(citation, "MedlineJournalInfo") {
            let issn = val(info, "ISSNLinking");
            if !issn.is_empty() {
                issns.push(issn);
            }
        }
        let date = if is_book {
            // A book series' start year is not the chapter's publication year.
            child(article, "ContributionDate").or_else(|| book.and_then(|b| child(b, "PubDate")))
        } else { journal
            .and_then(|j| child(j, "JournalIssue"))
            .and_then(|j| child(j, "PubDate")) };
        let year = date
            .map(|d| {
                let y = val(d, "Year");
                if y.is_empty() {
                    val(d, "MedlineDate").chars().take(4).collect()
                } else {
                    y
                }
            })
            .unwrap_or_default();
        let abstracts = child(article, "Abstract")
            .map(|a| {
                a.children()
                    .filter(|n| n.has_tag_name("AbstractText") && !text(*n).trim().is_empty())
                    .map(|n| {
                        let prefix = n
                            .attribute("Label")
                            .map(|s| format!("{s}: "))
                            .unwrap_or_default();
                        format!("{prefix}{}", text(n))
                    })
                    .collect::<Vec<_>>()
                    .join("\n")
            })
            .unwrap_or_default();
        let ids = child(node, if is_book { "PubmedBookData" } else { "PubmedData" }).and_then(|n| child(n, "ArticleIdList"));
        let id_value = |kind: &str| {
            let find = |n: roxmltree::Node| {
                n.children()
                    .find(|i| i.has_tag_name("ArticleId") && i.attribute("IdType") == Some(kind))
                    .map(text)
            };
            ids.and_then(find)
            .or_else(|| if is_book { child(article, "ArticleIdList").and_then(find) } else { None })
            .unwrap_or_default()
        };
        let source_title = if is_book { book.map(|b| val(b,"BookTitle")).unwrap_or_default() } else { journal.map(|j|val(j,"Title")).unwrap_or_default() };
        let data = json!({"pmid":pmid,"id":format!("PMID-{pmid}"),"title":val(article,"ArticleTitle"),"author":authors.join(", "),"journal":source_title,"year":year.parse::<u32>().unwrap_or(0),"abstract":abstracts,"issns":issns,"doi":id_value("doi"),"pmcid":id_value("pmc"),"recordType":if is_book {"book_chapter"} else {"journal_article"},"status":"abstract","tag":"PubMed","starred":false});
        out.push((pmid, data, xml[node.range()].to_string()));
    }
    Ok(out)
}
fn pack_xml(articles: &[String]) -> String {
    format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<PubmedArticleSet>\n{}\n</PubmedArticleSet>\n",
        articles.join("\n")
    )
}
const QUERY_CANCELLED: &str = "检索已中止，原有 XML 与已完成结果已保留";
fn check_query_cancel(cancel: Option<&Path>) -> R<()> {
    if cancel.is_some_and(Path::exists) { Err(QUERY_CANCELLED.into()) } else { Ok(()) }
}
fn query_wait(duration: Duration, cancel: Option<&Path>) -> R<()> {
    let start = std::time::Instant::now();
    loop {
        check_query_cancel(cancel)?;
        let remaining = duration.saturating_sub(start.elapsed());
        if remaining.is_zero() { return Ok(()); }
        std::thread::sleep(remaining.min(Duration::from_millis(50)));
    }
}
// Dropping this future cancels both a pending connection and a stalled body read.
// No detached request can later publish an XML result after cancellation.
fn ncbi_post(url: &str, fields: &[(String,String)], cancel: Option<&Path>) -> R<(reqwest::StatusCode,String)> {
    check_query_cancel(cancel)?;
    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build().map_err(err)?;
    runtime.block_on(async {
        let cli = reqwest::Client::builder().timeout(Duration::from_secs(100))
            .connect_timeout(Duration::from_secs(25)).user_agent("ScholarNoteLM/0.2 (literature research)")
            .redirect(reqwest::redirect::Policy::none()).build().map_err(err)?;
        let mut request = Box::pin(async {
            let response = cli.post(url).form(fields).send().await.map_err(|_| "PubMed 网络连接失败或超时".to_string())?;
            let status = response.status();
            let body = response.text().await.map_err(|_| "PubMed 响应读取失败或超时".to_string())?;
            Ok((status,body))
        });
        loop {
            check_query_cancel(cancel)?;
            match tokio::time::timeout(Duration::from_millis(50), &mut request).await {
                Ok(result) => { check_query_cancel(cancel)?; return result; }
                Err(_) => continue,
            }
        }
    })
}
fn ncbi(root: &Path, c: &Connection, endpoint: &str, mut fields: Vec<(String,String)>, cancel: Option<&Path>) -> R<String> {
    #[cfg(test)]
    if root.join("ncbi-fixture.json").is_file() {
        check_query_cancel(cancel)?;
        let path=root.join("ncbi-fixture.json");let mut fixture:Value=serde_json::from_slice(&fs::read(&path).map_err(err)?).map_err(err)?;
        let next=fixture["responses"].as_array_mut().ok_or("fixture responses")?;
        if next.is_empty(){return Err("Unexpected network request in test".into());}
        let response=next.remove(0);assert_eq!(response["endpoint"],endpoint);
        if endpoint=="esearch" {if let Some(term)=response["term"].as_str(){assert!(fields.iter().any(|(k,v)|k=="term" && v==term));assert!(!fields.iter().any(|(k,_)|k=="mindate"||k=="maxdate"));}else{assert!(fields.iter().any(|(k,v)|k=="term" && v.contains("hasabstract")));}}
        write_file(&path,fixture.to_string().as_bytes())?;return Ok(s(&response,"body").to_string());
    }
    let cfg = setting(c, "pubmed", json!({}))?;
    if !s(&cfg, "apiKey").is_empty() { fields.push(("api_key".into(), s(&cfg,"apiKey").into())); }
    if !s(&cfg, "email").is_empty() { fields.push(("email".into(), s(&cfg,"email").into())); }
    fields.push(("tool".into(), "ScholarNoteLM".into()));
    let lock = OpenOptions::new().create(true).truncate(false).read(true).write(true)
        .open(root.join("data/research/ncbi.lock")).map_err(err)?;
    loop {
        check_query_cancel(cancel)?;
        match lock.try_lock_exclusive() {
            Ok(()) => break,
            Err(e) if e.kind()==std::io::ErrorKind::WouldBlock => query_wait(Duration::from_millis(50),cancel)?,
            Err(e) => return Err(err(e)),
        }
    }
    let url = format!("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{endpoint}.fcgi");
    for attempt in 0..3 {
        query_wait(Duration::from_millis(360),cancel)?;
        let response = ncbi_post(&url,&fields,cancel);
        check_query_cancel(cancel)?;
        match response {
            Ok((status,body)) if status.is_success() => return Ok(body),
            Ok((status,_)) if status.as_u16()==429 || status.is_server_error() => {
                if attempt==2 { return Err(format!("PubMed 暂时不可用（HTTP {status}），旧结果已保留")); }
            }
            Ok((status,_)) => return Err(format!("PubMed 请求失败（HTTP {status}）")),
            Err(_) if attempt==2 => return Err("PubMed 网络连接失败或超时，旧结果已保留".into()),
            Err(_) => {},
        }
        query_wait(Duration::from_secs(2_u64.pow(attempt+1)),cancel)?;
    }
    Err("PubMed 请求失败".into())
}

fn validate_query(term: &str) -> R<()> {
    // ESearch can silently discard unknown field tags without returning a warning.
    // Names come from PubMed EInfo; short aliases from the official PubMed help.
    let fields = "all|all fields|uid|pmid|filt|filter|sb|subset|titl|title|ti|mesh|mesh terms|mh|majr|mesh major topic|jour|journal|ta|affl|affiliation|ad|ecno|ec/rn number|rn|subs|supplementary concept|nm|supplementary concept name|substance name|pdat|date - publication|dp|publication date|edat|date - entry|entry date|entrez date|vol|volume|vi|page|pagination|pg|ptyp|publication type|pt|lang|language|la|iss|issue|ip|subh|mesh subheading|sh|si|secondary source id|mhda|date - mesh|mesh date|tiab|title/abstract|otrm|other term|ot|tw|text word|word|coln|author - corporate|cn|corporate author|cnty|place of publication|pl|papx|pharmacological action|pa|grnt|grants and funding|gr|grant number|mdat|date - modification|modification date|lr|cdat|date - completion|completion date|dcom|pid|publisher id|aid|article identifier|faut|author - first|1au|first author|full|author|au|fau|full author name|finv|investigator|ir|fir|full investigator name|tt|transliterated title|laut|author - last|lastau|last author|ppdt|print publication date|epdt|electronic publication date|lid|location id|crdt|date - create|create date|crdat|book|ed|editor|isbn|pubn|publisher|aucl|author cluster id|eid|extended pmid|auid|author - identifier|author identifier|ps|subject - personal name|personal name as subject|cois|conflict of interest statements|conflict of interest statement";
    let mut quoted = false;
    let mut depth = 0i32;
    let mut field: Option<String> = None;
    for ch in term.chars() {
        if ch == '"' {
            quoted = !quoted;
            continue;
        }
        if quoted {
            continue;
        }
        if let Some(ref mut tag) = field {
            if ch == ']' {
                let value = tag.to_lowercase();
                let base = value.split(':').next().unwrap_or("").trim();
                if !fields.split('|').any(|f| f == base) {
                    return Err(format!("无法识别 PubMed 字段 [{tag}]。请更正字段标签，避免 PubMed 静默忽略该限制。"));
                }
                if let Some(modifier) = value.split_once(':').map(|(_, m)| m.trim()) {
                    if modifier != "noexp"
                        && !modifier
                            .strip_prefix('~')
                            .is_some_and(|n| !n.is_empty() && n.chars().all(|c| c.is_ascii_digit()))
                    {
                        return Err(format!("无法识别字段修饰符 [{tag}]"));
                    }
                }
                field = None;
            } else {
                tag.push(ch);
            }
        } else {
            match ch {
                '[' => field = Some(String::new()),
                ']' => return Err("字段方括号不匹配".into()),
                '(' => depth += 1,
                ')' => {
                    depth -= 1;
                    if depth < 0 {
                        return Err("检索式括号不匹配".into());
                    }
                }
                _ => {}
            }
        }
    }
    if quoted || depth != 0 || field.is_some() {
        return Err("检索式引号或括号不完整，请检查后重试".into());
    }
    Ok(())
}
fn search(root: &Path, c: &Connection, term: &str, f: &Value, retmax: usize, cancel: Option<&Path>) -> R<Value> {
    if term.trim().is_empty() || term.len() > 20000 {
        return Err("检索式为空或过长".into());
    }
    validate_query(term)?;
    let mut args = vec![
        ("db".into(), "pubmed".into()),
        ("term".into(), term.into()),
        ("retmode".into(), "json".into()),
        ("retmax".into(), retmax.to_string()),
        ("sort".into(), s(f, "sort").into()),
        ("datetype".into(), "pdat".into()),
    ];
    if !s(f, "start").is_empty() || !s(f, "end").is_empty() {
        args.push((
            "mindate".into(),
            if s(f, "start").is_empty() {
                "1000/01/01".into()
            } else {
                s(f, "start").replace('-', "/")
            },
        ));
        args.push((
            "maxdate".into(),
            if s(f, "end").is_empty() {
                "3000/12/31".into()
            } else {
                s(f, "end").replace('-', "/")
            },
        ));
    }
    let raw = ncbi(root, c, "esearch", args, cancel)?;
    let body: Value = serde_json::from_str(&raw).map_err(|_| "PubMed 返回格式异常")?;
    let r = &body["esearchresult"];
    if !body["error"].is_null() || r["count"].as_str().is_none() {
        return Err("PubMed 未返回有效结果".into());
    }
    if r["ERROR"].as_str().is_some()
        || r["errorlist"]["fieldsnotfound"]
            .as_array()
            .is_some_and(|a| !a.is_empty())
    {
        return Err(format!("PubMed 检索字段错误：{}", r["errorlist"]));
    }
    Ok(
        json!({"count":r["count"].as_str().unwrap().parse::<usize>().map_err(err)?,"translation":r["querytranslation"],"warnings":r["warninglist"],"errors":r["errorlist"],"ids":r["idlist"],"checked":now()}),
    )
}
fn collect_ids(root: &Path, c: &Connection, term: &str, f: &Value, depth: u8, cancel: Option<&Path>) -> R<Vec<String>> {
    let result = search(root, c, term, f, 10000, cancel)?;
    let count = result["count"].as_u64().unwrap_or(0);
    if count <= 10000 {
        let ids: Vec<String> = result["ids"]
            .as_array()
            .ok_or("PubMed 未返回 PMID 列表")?
            .iter()
            .filter_map(|v| v.as_str().map(String::from))
            .collect();
        if ids.len() != count as usize {
            return Err("PubMed 结果数量不一致，请重试".into());
        }
        return Ok(ids);
    }
    if depth > 24 {
        return Err("结果过大，请缩小检索范围".into());
    }
    use chrono::{Days, NaiveDate};
    let start = if s(f, "start").is_empty() {
        NaiveDate::from_ymd_opt(1800, 1, 1).unwrap()
    } else {
        NaiveDate::parse_from_str(s(f, "start"), "%Y-%m-%d").map_err(err)?
    };
    let end = if s(f, "end").is_empty() {
        NaiveDate::from_ymd_opt(chrono::Datelike::year(&chrono::Utc::now()) + 2, 12, 31).unwrap()
    } else {
        NaiveDate::parse_from_str(s(f, "end"), "%Y-%m-%d").map_err(err)?
    };
    let days = (end - start).num_days();
    if days <= 0 {
        return Err("单日命中超过 10000 条，请缩小研究范围后重试；未覆盖旧结果".into());
    }
    let mid = start
        .checked_add_days(Days::new((days / 2) as u64))
        .unwrap();
    let mut left = f.clone();
    left["start"] = json!(start.to_string());
    left["end"] = json!(mid.to_string());
    let mut right = f.clone();
    right["start"] = json!(mid.succ_opt().unwrap().to_string());
    right["end"] = json!(end.to_string());
    let mut ids = collect_ids(root, c, term, &left, depth + 1, cancel)?;
    ids.extend(collect_ids(root, c, term, &right, depth + 1, cancel)?);
    let mut seen = HashSet::new();
    ids.retain(|x| seen.insert(x.clone()));
    if ids.len() != count as usize {
        return Err(format!("分区检索计数不一致（预期 {count}，实际 {}），可能存在跨期发表日期或数据库更新，请缩小日期范围重试",ids.len()));
    }
    Ok(ids)
}
fn corpus(root: &Path, c: &Connection, p: &str) -> R<Value> {
    let j = ensure_jcr(root, c)?;
    let index = if !j.is_null() {
        Some(Jcr::load(root, s(&j, "version"))?)
    } else {
        None
    };
    let mut query_settings = serde_json::Map::new();
    let mut stmt=c.prepare("SELECT q.id,q.name,q.active_run,m.pmid,m.data,m.xml,q.source FROM queries q JOIN members m ON m.run_id=q.active_run WHERE q.project=? AND q.enabled=1 AND q.archived=0 ORDER BY q.rowid,m.position").map_err(err)?;
    let rows = stmt
        .query_map([p], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
                r.get::<_, String>(5)?,
                r.get::<_, String>(6)?,
            ))
        })
        .map_err(err)?;
    let mut papers: Vec<Value> = Vec::new();
    let mut positions = HashMap::new();
    let mut xmls = HashMap::new();
    let mut origins = Vec::new();
    let mut selected_counts:HashMap<String,usize>=HashMap::new();
    for row in rows {
        let (qid, name, run, pmid, data, xml, source) = row.map_err(err)?;
        let f = if let Some(f) = query_settings.get(&qid) {
            f.clone()
        } else {
            let f = query_filters(c, &qid)?;
            query_settings.insert(qid.clone(), f.clone());
            f
        };
        let enabled = source != "zotero" && f["jcr"] == true;
        if enabled && index.is_none() {
            return Err("请先上传并校验 JCR 文件".into());
        }
        let mut paper: Value = serde_json::from_str(&data).map_err(err)?;
        let matches = index
            .as_ref()
            .map(|idx| idx.matched(&paper))
            .unwrap_or_default();
        let known = matches.iter().any(|r| !s(r, "quartile").is_empty());
        let eligible=source=="zotero" || qualifies(&paper,&f,index.as_ref());
        let selected=selected_counts.entry(qid.clone()).or_default();
        let keep=eligible && (source=="zotero" || source=="import" || f["mode"]=="full" || *selected<f["limit"].as_u64().unwrap_or(30) as usize);
        if keep {*selected+=1;}
        let pos = if let Some(i) = positions.get(&pmid) {
            *i
        } else {
            paper["jcr"] = json!(matches);
            paper["included"] = json!(false);
            paper["reason"] = json!(if s(&paper,"abstract").trim().is_empty(){"XML 无有效摘要"}else if eligible{"超过该检索式的目标数量"}else{"不满足来源检索式的 JCR 条件"});
            paper["sources"] = json!([]);
            let i = papers.len();
            papers.push(paper);
            positions.insert(pmid.clone(), i);
            xmls.insert(pmid.clone(), xml);
            i
        };
        if keep {
            papers[pos]["included"] = json!(true);
            papers[pos]["reason"] = json!(if source=="zotero" { "Zotero 导入来源" } else if !enabled {
                "至少一个来源未限制 JCR"
            } else if !known {
                "JCR 未匹配 / 无分区，按来源规则保留"
            } else {
                "满足至少一个来源的 JCR 条件"
            });
        }
        papers[pos]["sources"]
            .as_array_mut()
            .unwrap()
            .push(json!({"id":qid,"name":name,"run":run,"included":keep}));
        origins.push(json!([qid, run, pmid]));
    }
    let included: Vec<_> = papers.iter().filter(|x| x["included"] == true).collect();
    let pmids: Vec<_> = included.iter().map(|x| s(x, "pmid")).collect();
    let active: Vec<Value> = {
        let mut st=c.prepare("SELECT id,active_run FROM queries WHERE project=? AND enabled=1 AND archived=0 AND active_run IS NOT NULL ORDER BY id").map_err(err)?;
        let values = st
            .query_map([p], |r| {
                Ok(json!([r.get::<_, String>(0)?, r.get::<_, String>(1)?]))
            })
            .map_err(err)?
            .collect::<Result<Vec<_>, _>>()
            .map_err(err)?;
        values
    };
    let manifest = json!({"selectionPolicy":SELECTION_POLICY,"project":p,"queryFilters":query_settings,"jcrVersion":j["version"],"pmids":pmids,"activeRuns":active,"origins":origins});
    let signature = hash(manifest.to_string().as_bytes());
    let old: Option<(String, String)> = c
        .query_row(
            "SELECT id,signature FROM corpora WHERE project=? ORDER BY rowid DESC LIMIT 1",
            [p],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(err)?;
    let id = if old.as_ref().is_some_and(|(_, sig)| sig == &signature) {
        old.unwrap().0
    } else {
        let id = uid();
        let dir = project_dir(root,p)?.join(format!("pubmed/snapshots/{id}"));
        let nodes: Vec<_> = pmids
            .iter()
            .filter_map(|id| xmls.get(*id).cloned())
            .collect();
        write_file(&dir.join("pubmed.xml"), pack_xml(&nodes).as_bytes())?;
        write_file(&dir.join("manifest.json"), manifest.to_string().as_bytes())?;
        c.execute(
            "INSERT INTO corpora VALUES(?,?,?,?,?)",
            params![id, p, now(), signature, manifest.to_string()],
        )
        .map_err(err)?;
        id
    };
    // Repairable projection: SQLite + immutable snapshot remain authoritative.
    let src = project_dir(root,p)?.join(format!("pubmed/snapshots/{id}/pubmed.xml"));
    let current = project_dir(root,p)?.join("pubmed/current.xml");
    let bytes = fs::read(src).map_err(err)?;
    // Preserve the source identity on a read; dependent status caches invalidate
    // only when the published corpus actually changes. Missing projections heal.
    if fs::read(&current).ok().as_deref() != Some(bytes.as_slice()) {
        write_file(&current, &bytes)?;
    }
    let no_abstract:Vec<_>=papers.iter().filter(|a|a["included"]!=true && s(a,"abstract").trim().is_empty()).map(|a|json!({"pmid":a["pmid"],"reason":"XML 无有效摘要"})).collect();
    write_file(&project_dir(root,p)?.join("metadata/abstract-exclusions.json"),serde_json::to_string(&no_abstract).map_err(err)?.as_bytes())?;
    let file_sync = download_rpc(root, "reconcile", json!({"project":p}));
    Ok(
        json!({"files":file_sync.unwrap_or_else(|e|json!({"error":e})),"snapshot":id,"papers":papers,"included":pmids.len(),"excluded":papers.len()-pmids.len(),"path":project_dir(root,p)?.join("pubmed/current.xml").to_string_lossy()}),
    )
}
fn workspace(root: &Path, c: &Connection, p: &str) -> R<Value> {
    valid_id(p)?;
    let mut stmt=c.prepare("SELECT id,name,text,source,revision,enabled,archived,active_run,last_error FROM queries WHERE project=? ORDER BY rowid").map_err(err)?;
    let rows=stmt.query_map([p],|r|Ok(json!({"id":r.get::<_,String>(0)?,"name":r.get::<_,String>(1)?,"text":r.get::<_,String>(2)?,"source":r.get::<_,String>(3)?,"revision":r.get::<_,u32>(4)?,"enabled":r.get::<_,bool>(5)?,"archived":r.get::<_,bool>(6)?,"activeRun":r.get::<_,Option<String>>(7)?,"error":r.get::<_,String>(8)?}))).map_err(err)?;
    let zotero_job=zotero_import::status(root,p)?;
    let mut queries = Vec::new();
    for r in rows {
        let mut q = r.map_err(err)?;
        let f = query_filters(c, s(&q, "id"))?;
        q["filters"] = f.clone();
        if let Some(run) = q["activeRun"].as_str() {
            let data: String = c
                .query_row("SELECT data FROM runs WHERE id=?", [run], |r| r.get(0))
                .map_err(err)?;
            q["run"] = serde_json::from_str(&data).map_err(err)?;
            q["xmlExists"] = json!(project_file(root,p,s(&q["run"], "xmlPath"))?.is_file());
            q["stale"] = json!(q["source"]!="zotero" && q["source"]!="import" && (query_fetch_stale(&q["run"],s(&q,"text"),&f) || (f["jcr"]==true && q["run"]["jcrVersion"]!=ensure_jcr(root,c)?["version"])));
        }
        if q["source"]=="zotero" {q["zoteroJob"]=zotero_import::source_job(root,p,&q)?;}
        queries.push(q);
    }
    Ok(
        json!({"queries":queries,"sourceBusy":(["queued","running"].contains(&s(&zotero_job,"state"))),"chats":chat_list(c,p)?,"corpus":corpus(root,c,p)?}),
    )
}
const SELECTION_POLICY: u64 = 2;
fn same_candidate_search(run: &Value, term: &str, filters: &Value) -> bool {
    run["selectionPolicy"]==SELECTION_POLICY && s(run,"text").trim()==term.trim()
        && ["start","end","sort","mode"].iter().all(|k|run["filters"][k]==filters[k])
}
fn query_fetch_stale(run: &Value, text: &str, filters: &Value) -> bool {
    !same_candidate_search(run,text,filters) || ["limit","jcr","quartiles","unknown"].iter().any(|k|run["filters"][k]!=filters[k])
}
fn qualifies(paper: &Value, filters: &Value, index: Option<&Jcr>) -> bool {
    if s(paper,"abstract").trim().is_empty() {return false;}
    if filters["jcr"]!=true {return true;}
    let matches=index.map(|j|j.matched(paper)).unwrap_or_default();
    if !matches.iter().any(|r|!s(r,"quartile").is_empty()) {return false;}
    matches.iter().any(|r|filters["quartiles"].as_array().is_some_and(|qs|qs.contains(&r["quartile"])))
}
fn run_query(root: &Path, c: &mut Connection, p: &str, id: &str, cancel: Option<&Path>, force: bool) -> R<Value> {
    let source:String=c.query_row("SELECT source FROM queries WHERE id=? AND project=?",params![id,p],|r|r.get(0)).map_err(err)?;
    if source=="zotero" {return Err("Zotero 来源是导入快照，不能执行检索；请使用导入自 Zotero 创建新的来源".into());}
    check_query_cancel(cancel)?;
    let (term, revision): (String, u32) = c
        .query_row(
            "SELECT text,revision FROM queries WHERE id=? AND project=? AND archived=0",
            params![id, p],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .map_err(|_| "检索式不存在或已归档")?;
    let f = query_filters(c, id)?;
    if term.trim().is_empty() {
        return Err("请先填写检索式".into());
    }
    let j=ensure_jcr(root,c)?;
    let index=if j.is_null(){None}else{Some(Jcr::load(root,s(&j,"version"))?)};
    if f["jcr"]==true && index.is_none(){return Err("请先上传并校验 JCR 文件".into());}
    let old:Option<String>=c.query_row("SELECT r.data FROM queries q JOIN runs r ON r.id=q.active_run WHERE q.id=?",[id],|r|r.get(0)).optional().map_err(err)?;
    let old=old.and_then(|v|serde_json::from_str::<Value>(&v).ok());
    let reusable=old.as_ref().filter(|r|!force && same_candidate_search(r,&term,&f));
    let mut articles=Vec::new();
    let (ids,count,probe)=if let Some(previous)=reusable.filter(|r|project_file(root,p,s(r,"candidateIdsPath")).ok().is_some_and(|f|f.is_file())) {
        let ids:Vec<String>=serde_json::from_slice(&fs::read(project_file(root,p,s(previous,"candidateIdsPath"))?).map_err(err)?).map_err(err)?;
        let mut stmt=c.prepare("SELECT pmid,data,xml FROM members WHERE run_id=? ORDER BY position").map_err(err)?;
        let rows=stmt.query_map([s(previous,"id")],|r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?))).map_err(err)?;
        for row in rows {let (id,data,xml)=row.map_err(err)?;articles.push((id,serde_json::from_str::<Value>(&data).map_err(err)?,xml));}
        (ids,previous["count"].as_u64().unwrap_or(0) as usize,previous.clone())
    } else {
        let effective=format!("({term}) AND hasabstract");
        let probe=search(root,c,&effective,&f,10000,cancel)?;
        let count=probe["count"].as_u64().unwrap_or(0) as usize;
        let ids=if f["mode"]=="full" {collect_ids(root,c,&effective,&f,0,cancel)?}else{probe["ids"].as_array().ok_or("PubMed PMID 列表缺失")?.iter().filter_map(|v|v.as_str().map(String::from)).collect::<Vec<_>>()};
        if ids.len()!=count.min(if f["mode"]=="full"{usize::MAX}else{10000}) {return Err("PubMed 候选数量发生变化，请重试；旧结果已保留".into());}
        (ids,count,probe)
    };
    let target=if f["mode"]=="full"{usize::MAX}else{f["limit"].as_u64().unwrap_or(30) as usize};
    let run=uid();let dir=project_dir(root,p)?.join(format!("pubmed/queries/{id}/runs/{run}"));fs::create_dir_all(&dir).map_err(err)?;
    let mut offset=articles.len();
    while offset<ids.len() && articles.iter().filter(|(_,a,_)|qualifies(a,&f,index.as_ref())).count()<target {
        check_query_cancel(cancel)?;
        let end=(offset+100).min(ids.len());let batch=&ids[offset..end];
        let raw=ncbi(root,c,"efetch",vec![("db".into(),"pubmed".into()),("retmode".into(),"xml".into()),("id".into(),batch.join(","))],cancel)?;
        write_file(&dir.join(format!("batch-{offset}.xml")),raw.as_bytes())?;
        let mut fetched=parse_pubmed(&raw)?;
        let got:HashSet<_>=fetched.iter().map(|x|x.0.as_str()).collect();
        let requested:HashSet<_>=batch.iter().map(String::as_str).collect();
        if got!=requested || fetched.len()!=batch.len(){return Err("PubMed XML 记录不完整，未作为无摘要排除；旧结果已保留".into());}
        fetched.sort_by_key(|x|batch.iter().position(|id|id==&x.0).unwrap_or(usize::MAX));
        articles.extend(fetched);offset=end;
    }
    let selected=articles.iter().filter(|(_,a,_)|qualifies(a,&f,index.as_ref())).count().min(target);
    let candidate_ids_path=format!("pubmed/queries/{id}/runs/{run}/candidate-ids.json");
    write_file(&dir.join("candidate-ids.json"),serde_json::to_string(&ids).map_err(err)?.as_bytes())?;
    let ids=ids[..offset].to_vec();
    let got: HashSet<_> = articles.iter().map(|x| x.0.as_str()).collect();
    let requested: HashSet<_> = ids.iter().map(String::as_str).collect();
    if got != requested {
        let mut missing: Vec<_> = requested.difference(&got).copied().collect();missing.sort_unstable();
        let mut unexpected: Vec<_> = got.difference(&requested).copied().collect();unexpected.sort_unstable();
        return Err(format!("PubMed XML 记录不匹配：请求 {} 条，解析 {} 条；缺失 PMID：{}；额外 PMID：{}。批次 XML 已保留，未覆盖旧结果",requested.len(),got.len(),missing.join(", "),unexpected.join(", ")));
    }
    let positions: HashMap<_, _> = ids
        .iter()
        .enumerate()
        .map(|(i, id)| (id.as_str(), i))
        .collect();
    articles.sort_by_key(|a| positions.get(a.0.as_str()).copied().unwrap_or(usize::MAX));
    let data = json!({"id":run,"revision":revision,"text":term,"filters":f,"created":now(),"count":count,"fetched":articles.len(),"qualified":selected,"target":if target==usize::MAX {count}else{target},"exhausted":offset>=count,"candidateLimitReached":offset>=10000 && offset<count,"selectionPolicy":SELECTION_POLICY,"candidateIdsPath":candidate_ids_path,"jcrVersion":j["version"],"truncated":articles.len()<count,"translation":probe["translation"],"warnings":probe["warnings"],"meshVersion":mesh_status(root,c)?["version"],"xmlPath":format!("pubmed/queries/{id}/runs/{run}/raw.xml")});
    write_file(
        &dir.join("raw.xml"),
        pack_xml(&articles.iter().map(|x| x.2.clone()).collect::<Vec<_>>()).as_bytes(),
    )?;
    write_file(&dir.join("manifest.json"), data.to_string().as_bytes())?;
    let _commit_lock = project_lock(root, p)?;
    check_query_cancel(cancel)?;
    let tx = c.transaction().map_err(err)?;
    tx.execute(
        "INSERT INTO runs VALUES(?,?,?,?,?)",
        params![run, id, revision, now(), data.to_string()],
    )
    .map_err(err)?;
    for (i, (pmid, a, xml)) in articles.iter().enumerate() {
        tx.execute("INSERT INTO articles VALUES(?,?,?) ON CONFLICT(pmid) DO UPDATE SET data=excluded.data,xml=excluded.xml",params![pmid,a.to_string(),xml]).map_err(err)?;
        tx.execute(
            "INSERT INTO members VALUES(?,?,?,?,?)",
            params![run, pmid, i, a.to_string(), xml],
        )
        .map_err(err)?;
    }
    let changed=tx.execute("UPDATE queries SET active_run=?,last_error='' WHERE id=? AND project=? AND revision=? AND archived=0",params![run,id,p,revision]).map_err(err)?;
    tx.commit().map_err(err)?;
    if changed == 0 {
        return Err("执行期间检索式已修改或归档。本次结果已留存，但未覆盖当前版本。".into());
    }
    workspace(root, c, p)
}

fn mesh_status(root: &Path, c: &Connection) -> R<Value> {
    let mut m = setting(c, "mesh", json!({"version":"","records":0,"terms":0}))?;
    m["autoUpdate"] = setting(c, "meshAuto", json!(true))?;
    m["includeScrPreference"] = setting(c, "meshScr", json!(false))?;
    m["intervalDays"] = json!(7);
    m["job"] = setting(c, "meshJob", json!({"state":"idle"}))?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(root.join("data/research/mesh.lock"))
        .map_err(err)?;
    let running = lock.try_lock_exclusive().is_err();
    m["running"] = json!(running);
    if !running && m["job"]["state"] == "running" {
        m["job"] =
            json!({"state":"interrupted","message":"上次更新被中断，旧索引仍可使用，请重新更新"});
    }
    Ok(m)
}
fn mesh_lookup(root: &Path, c: &Connection, query: &str, limit: usize) -> R<Value> {
    mesh_lookup_at(root, &setting(c, "mesh", Value::Null)?, query, limit)
}
fn mesh_lookup_at(root: &Path, m: &Value, query: &str, limit: usize) -> R<Value> {
    if s(&m, "path").is_empty() {
        return Ok(json!([]));
    }
    let conn = Connection::open_with_flags(
        root.join(s(&m, "path")),
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )
    .map_err(err)?;
    let tokens: Vec<_> = query
        .split(|c: char| !c.is_alphanumeric())
        .filter(|s| !s.is_empty())
        .take(12)
        .map(|s| format!("\"{}\"*", s.replace('"', "")))
        .collect();
    if tokens.is_empty() {
        return Ok(json!([]));
    }
    let mut st=conn.prepare("SELECT d.data FROM terms JOIN descriptors d ON d.id=terms.id WHERE terms MATCH ? ORDER BY rank LIMIT ?").map_err(err)?;
    let found = st
        .query_map(params![tokens.join(" AND "), limit.min(30)], |r| {
            r.get::<_, String>(0)
        })
        .map_err(err)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(err)?;
    Ok(json!(found
        .into_iter()
        .filter_map(|s| serde_json::from_str::<Value>(&s).ok())
        .collect::<Vec<_>>()))
}
fn mesh_record(xml: &str, kind: &str) -> R<Value> {
    let doc = roxmltree::Document::parse(xml).map_err(err)?;
    let n = doc.root_element();
    let (idtag, nametag) = match kind {
        "descriptor" => ("DescriptorUI", "DescriptorName"),
        "qualifier" => ("QualifierUI", "QualifierName"),
        _ => ("SupplementalRecordUI", "SupplementalRecordName"),
    };
    let id = val(n, idtag);
    let label = child(n, nametag).map(text).unwrap_or_default();
    if id.is_empty() || label.is_empty() {
        return Err("MeSH 数据记录缺少标识或名称".into());
    }
    let mut terms: Vec<_> = n
        .descendants()
        .filter(|x| x.has_tag_name("Term"))
        .filter_map(|x| child(x, "String").map(text))
        .collect();
    terms.sort();
    terms.dedup();
    let scope = n
        .descendants()
        .find(|x| x.has_tag_name("ScopeNote"))
        .map(text)
        .unwrap_or_default();
    let trees: Vec<_> = n
        .descendants()
        .filter(|x| x.has_tag_name("TreeNumber"))
        .map(text)
        .collect();
    let qualifiers:Vec<_>=n.descendants().filter(|x|x.has_tag_name("AllowableQualifier")).filter_map(|x|child(x,"QualifierReferredTo")).map(|x|json!({"id":val(x,"QualifierUI"),"label":child(x,"QualifierName").map(text).unwrap_or_default()})).collect();
    let mapped: Vec<_> = n
        .descendants()
        .filter(|x| x.has_tag_name("HeadingMappedTo"))
        .map(|x| { let referred=child(x,"DescriptorReferredTo").unwrap_or(x); json!({"id":val(referred,"DescriptorUI"),"label":child(referred,"DescriptorName").map(text).unwrap_or_default()}) })
        .collect();
    Ok(
        json!({"id":id,"label":label,"kind":kind,"terms":terms,"scope":scope,"trees":trees,"qualifiers":qualifiers,"mappedTo":mapped}),
    )
}
fn index_mesh_file(conn: &mut Connection, path: &Path, kind: &str) -> R<(usize, usize)> {
    use quick_xml::{events::Event, Reader as XmlReader, Writer};
    let file = File::open(path).map_err(err)?;
    let input: Box<dyn Read> = if path.extension().is_some_and(|e| e == "gz") {
        Box::new(flate2::read::GzDecoder::new(file))
    } else {
        Box::new(file)
    };
    let mut reader = XmlReader::from_reader(BufReader::new(input));
    let mut buf = Vec::new();
    let mut writer: Option<Writer<Vec<u8>>> = None;
    let mut records = 0;
    let mut termcount = 0;
    let target = match kind {
        "descriptor" => "DescriptorRecord",
        "qualifier" => "QualifierRecord",
        _ => "SupplementalRecord",
    };
    let root_tag = format!("{target}Set");
    let mut closed_root = false;
    let tx = conn.transaction().map_err(err)?;
    loop {
        let event = reader.read_event_into(&mut buf).map_err(err)?;
        match &event {
            Event::Start(e) if e.name().as_ref() == target.as_bytes() => {
                writer = Some(Writer::new(Vec::new()));
            }
            Event::End(e) if e.name().as_ref() == root_tag.as_bytes() => {
                closed_root = true;
            }
            Event::Eof => break,
            _ => {}
        }
        let ended = matches!(&event,Event::End(e) if e.name().as_ref()==target.as_bytes());
        if let Some(w) = writer.as_mut() {
            w.write_event(event.into_owned()).map_err(err)?;
        }
        if ended {
            let xml = String::from_utf8(writer.take().ok_or("MeSH XML 结构错误")?.into_inner())
                .map_err(err)?;
            let value = mesh_record(&xml, kind)?;
            tx.execute(
                "INSERT INTO descriptors VALUES(?,?)",
                params![s(&value, "id"), value.to_string()],
            )
            .map_err(err)?;
            let terms = value["terms"]
                .as_array()
                .unwrap()
                .iter()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>();
            termcount += terms.len();
            tx.execute(
                "INSERT INTO terms(id,label,synonyms) VALUES(?,?,?)",
                params![s(&value, "id"), s(&value, "label"), terms.join(" ")],
            )
            .map_err(err)?;
            records += 1;
        }
        buf.clear();
    }
    if records == 0 || !closed_root || writer.is_some() {
        return Err(format!("MeSH {kind} 数据为空，未替换现有索引"));
    }
    tx.commit().map_err(err)?;
    Ok((records, termcount))
}
fn mesh_update_inner(root: &Path, c: &Connection, force: bool) -> R<Value> {
    let base = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/";
    let cli = client(900)?;
    put(
        c,
        "meshJob",
        &json!({"state":"running","message":"正在检查 NLM 官方生产版数据","started":now()}),
    )?;
    let html = cli
        .get(base)
        .send()
        .map_err(|_| "无法连接 NLM 数据目录")?
        .error_for_status()
        .map_err(|_| "NLM 数据目录暂时不可用")?
        .text()
        .map_err(err)?;
    let re = regex::Regex::new(r"desc(\d{4})\.gz").unwrap();
    let year = re
        .captures_iter(&html)
        .filter_map(|c| c[1].parse::<u32>().ok())
        .max()
        .ok_or("未发现官方 MeSH 生产版，现有索引未变更")?;
    let include_scr = setting(c, "meshScr", json!(false))? == true;
    let mut files = vec![
        (format!("desc{year}.gz"), "descriptor"),
        (format!("qual{year}.xml"), "qualifier"),
    ];
    if include_scr {
        files.push((format!("supp{year}.gz"), "supplemental"));
    }
    let previous = setting(c, "mesh", json!({}))?;
    let mut remote = Vec::new();
    for (name, kind) in &files {
        let url = format!("{base}{name}");
        let h = cli
            .head(&url)
            .send()
            .map_err(|_| "MeSH 版本检查连接失败")?
            .error_for_status()
            .map_err(|_| "MeSH 版本检查失败")?;
        remote.push(json!({"name":name,"kind":kind,"url":url,"etag":h.headers().get("etag").and_then(|v|v.to_str().ok()).unwrap_or(""),"modified":h.headers().get("last-modified").and_then(|v|v.to_str().ok()).unwrap_or("")}));
    }
    let has_validators = remote
        .iter()
        .all(|r| !s(r, "etag").is_empty() || !s(r, "modified").is_empty());
    if !force
        && previous["schemaVersion"] == 2
        && has_validators
        && previous["remote"] == json!(remote)
        && !s(&previous, "path").is_empty()
        && root.join(s(&previous, "path")).is_file()
    {
        let mut m = previous;
        m["checked"] = json!(now());
        put(c, "mesh", &m)?;
        return Ok(m);
    }
    let version = format!("{year}-{}", uid());
    let dir = root.join(format!("data/reference/mesh/{version}"));
    fs::create_dir_all(&dir).map_err(err)?;
    let mut manifest = Vec::new();
    for entry in &remote {
        let name = s(entry, "name");
        // Reuse only a byte-verified official source from a previous snapshot.
        if has_validators
            && previous["remote"]
                .as_array()
                .is_some_and(|a| a.contains(entry))
        {
            if let Some(old_file) = previous["files"]
                .as_array()
                .and_then(|a| a.iter().find(|v| s(v, "name") == name))
            {
                let old_path = root
                    .join(s(&previous, "path"))
                    .parent()
                    .map(|p| p.join(name));
                if let Some(path) = old_path.filter(|p| p.is_file()) {
                    let bytes = fs::read(&path).map_err(err)?;
                    if hash(&bytes) == s(old_file, "sha256") {
                        write_file(&dir.join(name), &bytes)?;
                        manifest.push(old_file.clone());
                        continue;
                    }
                }
            }
        }
        put(
            c,
            "meshJob",
            &json!({"state":"running","message":format!("正在下载 {name}"),"started":now()}),
        )?;
        let mut response = cli
            .get(s(entry, "url"))
            .send()
            .map_err(|_| "MeSH 下载连接失败")?
            .error_for_status()
            .map_err(|_| "MeSH 下载失败")?;
        let expected_length = response.content_length();
        let part = dir.join(format!("{name}.part"));
        let mut out = File::create(&part).map_err(err)?;
        let mut digest = Sha256::new();
        let mut total = 0u64;
        let mut bytes = [0u8; 65536];
        loop {
            let n = response.read(&mut bytes).map_err(err)?;
            if n == 0 {
                break;
            }
            total += n as u64;
            if total > 2_000_000_000 {
                return Err("MeSH 文件超出预期大小，下载已终止".into());
            }
            out.write_all(&bytes[..n]).map_err(err)?;
            digest.update(&bytes[..n]);
        }
        out.sync_all().map_err(err)?;
        if expected_length.is_some_and(|n| n != total) {
            return Err("MeSH 下载不完整，旧索引已保留".into());
        }
        fs::rename(part, dir.join(name)).map_err(err)?;
        manifest
            .push(json!({"name":name,"bytes":total,"sha256":format!("{:x}",digest.finalize())}));
    }
    let path = dir.join("index.sqlite3");
    let mut conn = Connection::open(&path).map_err(err)?;
    conn.execute_batch("CREATE TABLE descriptors(id TEXT PRIMARY KEY,data TEXT NOT NULL);CREATE VIRTUAL TABLE terms USING fts5(id UNINDEXED,label,synonyms,tokenize='unicode61');").map_err(err)?;
    let mut counts = serde_json::Map::new();
    let mut records = 0;
    let mut terms = 0;
    for (name, kind) in &files {
        put(
            c,
            "meshJob",
            &json!({"state":"running","message":format!("正在建立本地 {kind} 索引"),"started":now()}),
        )?;
        let (n, t) = index_mesh_file(&mut conn, &dir.join(name), kind)?;
        counts.insert(kind.to_string(), json!(n));
        records += n;
        terms += t;
    }
    if counts
        .get("descriptor")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        < 25000
    {
        return Err("MeSH 主词条数量异常，未切换索引".into());
    }
    let check: String = conn
        .query_row("PRAGMA integrity_check", [], |r| r.get(0))
        .map_err(err)?;
    if check != "ok" {
        return Err("MeSH 数据库完整性校验失败".into());
    }
    conn.execute("INSERT INTO terms(terms) VALUES('optimize')", [])
        .map_err(err)?;
    drop(conn);
    let m = json!({"schemaVersion":2,"version":version,"year":year,"records":records,"terms":terms,"counts":counts,"includeScr":include_scr,"path":format!("data/reference/mesh/{version}/index.sqlite3"),"built":now(),"checked":now(),"remote":remote,"files":manifest});
    write_file(
        &dir.join("manifest.json"),
        serde_json::to_vec_pretty(&m).map_err(err)?.as_slice(),
    )?;
    put(c, "mesh", &m)?;
    Ok(m)
}
pub fn update_mesh(root: &Path, force: bool) -> R<Value> {
    let c = db(root)?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(root.join("data/research/mesh.lock"))
        .map_err(err)?;
    lock.try_lock_exclusive()
        .map_err(|_| "MeSH 更新正在进行中")?;
    let result = mesh_update_inner(root, &c, force);
    match &result {
        Ok(_) => put(
            &c,
            "meshJob",
            &json!({"state":"done","message":"MeSH 索引已就绪","finished":now()}),
        )?,
        Err(e) => put(
            &c,
            "meshJob",
            &json!({"state":"error","message":e,"finished":now()}),
        )?,
    }
    result
}
pub fn auto_mesh(root: &Path) {
    if let Ok(c) = db(root) {
        let enabled = setting(&c, "meshAuto", json!(true)).unwrap_or(json!(true)) == true;
        let m = setting(&c, "mesh", json!({})).unwrap_or(json!({}));
        let job = setting(&c, "meshJob", json!({})).unwrap_or(json!({}));
        if enabled
            && now().saturating_sub(m["checked"].as_u64().unwrap_or(0)) >= 7 * 86400
            && now().saturating_sub(job["finished"].as_u64().unwrap_or(0)) > 6 * 3600
        {
            let _ = update_mesh(root, false);
        }
    }
}

fn public_profile(mut p: Value) -> Value {
    if !p["models"].is_array() {
        p["models"] = if s(&p, "model").is_empty() { json!([]) } else { json!([s(&p,"model")]) };
    }
    p["hasKey"] = json!(!s(&p, "apiKey").is_empty());
    p.as_object_mut().map(|o| o.remove("apiKey"));
    p
}
fn profile(c: &Connection, p: &Value) -> R<Value> {
    let profiles = setting(c, "profiles", json!([]))?;
    let mut value = if !p["profile"].is_null() {
        p["profile"].clone()
    } else {
        let active = if s(p,"profileId").is_empty() { setting(c, "activeProfile", json!(""))? } else { p["profileId"].clone() };
        profiles
            .as_array()
            .unwrap()
            .iter()
            .find(|v| v["id"] == active)
            .cloned()
            .ok_or("请在设置中配置并启用 LLM")?
    };
    if !s(p,"model").is_empty() && p["profile"].is_null() {
        let model=s(p,"model");
        if !value["models"].as_array().is_some_and(|models| models.iter().any(|v| v.as_str()==Some(model))) && s(&value,"model")!=model {
            return Err("所选模型已移除，请重新选择".into());
        }
        value["model"]=json!(model);
    }
    if s(&value, "apiKey").trim().is_empty() {
        if let Some(old) = profiles
            .as_array()
            .unwrap()
            .iter()
            .find(|v| v["id"] == value["id"])
        {
            value["apiKey"] = old["apiKey"].clone();
        }
    }
    if value["clearKey"] == true {
        value["apiKey"] = json!("");
    }
    Ok(value)
}
fn llm_url(p: &Value, suffix: &str) -> R<String> {
    let base = s(p, "baseUrl").trim().trim_end_matches('/');
    let url = reqwest::Url::parse(base).map_err(|_| "请输入完整的模型 Base URL")?;
    if !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("Base URL 不能包含账户、查询参数或片段".into());
    }
    if url.scheme() != "https"
        && !(url.scheme() == "http"
            && ["127.0.0.1", "localhost", "[::1]", "::1"].contains(&url.host_str().unwrap_or("")))
    {
        return Err("模型接口须使用 HTTPS；本机服务可使用 HTTP".into());
    }
    let base = base.strip_suffix("/chat/completions").or_else(|| base.strip_suffix("/models")).unwrap_or(base);
    let normalized = reqwest::Url::parse(base).map_err(|_| "模型地址无效")?;
    let base = if normalized.path().trim_matches('/').is_empty() {
        format!("{base}/v1")
    } else {
        base.to_string()
    };
    Ok(format!("{base}/{suffix}"))
}
// The blocking client's timeout applies to each read. Any received reasoning chunk
// therefore keeps a live response alive; there is no overall generation deadline.
fn llm_stream(p: &Value, messages: Value, emit: &mut dyn FnMut(&str, &str) -> R<bool>) -> R<()> {
    if s(p, "model").is_empty() {
        return Err("请填写模型名称".into());
    }
    let mut body = json!({"model":p["model"],"messages":messages,"stream":true});
    if p["temperature"].is_number() {
        body["temperature"] = p["temperature"].clone();
    }
    let mut req = model_client(p["timeout"].as_u64().unwrap_or(120).clamp(10, 600))?
        .post(llm_url(p, "chat/completions")?)
        .json(&body);
    if !s(p, "apiKey").is_empty() {
        req = req.bearer_auth(s(p, "apiKey"));
    }
    let response = req
        .send()
        .map_err(|_| "模型连接失败或等待响应超时，请检查地址和网络")?;
    if !response.status().is_success() {
        return Err(format!(
            "模型请求失败（HTTP {}），请检查地址、模型和参数兼容性",
            response.status()
        ));
    }
    let is_json = response
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.contains("application/json"));
    let mut received = false;
    let mut process = |v: Value| -> R<bool> {
        if !v["error"].is_null() {
            return Err("模型服务返回流式错误，请检查服务商状态或请求参数".into());
        }
        let choice = &v["choices"][0];
        let d = if choice["delta"].is_object() {
            &choice["delta"]
        } else {
            &choice["message"]
        };
        let content = stream_text(&d["content"]);
        let mut reasoning = stream_text(&d["reasoning_content"]);
        if reasoning.is_empty() {
            reasoning = stream_text(&d["reasoning"]);
        }
        if reasoning.is_empty() {
            if let Some(parts) = d["reasoning_details"].as_array() {
                for part in parts {
                    reasoning.push_str(s(part, "text"));
                }
            }
        }
        if !content.is_empty() || !reasoning.is_empty() {
            received = true;
            return emit(&content, &reasoning);
        }
        Ok(true)
    };
    if is_json {
        process(response.json().map_err(|_| "模型接口未返回有效 JSON")?)?;
        if !received {
            return Err("模型未返回文本或推理内容".into());
        }
        return Ok(());
    }
    let mut reader = BufReader::new(response);
    let mut line = String::new();
    let mut payload = String::new();
    let mut finished = false;
    loop {
        line.clear();
        let bytes = reader
            .read_line(&mut line)
            .map_err(|_| "模型数据流中断或等待新数据超时，已收到的内容已保留")?;
        if bytes == 0 && payload.is_empty() {
            break;
        }
        if bytes == 0 || line.trim().is_empty() {
            if !payload.is_empty() {
                if payload.trim() == "[DONE]" {
                    finished = true;
                    break;
                }
                let v: Value = serde_json::from_str(payload.trim())
                    .map_err(|_| "模型返回了无效的流式数据，已收到的内容已保留")?;
                if v["choices"][0]["finish_reason"].is_string() {
                    finished = true;
                }
                if !process(v)? {
                    return Ok(());
                }
                payload.clear();
            }
            if bytes == 0 {
                break;
            }
        } else if let Some(data) = line.strip_prefix("data:") {
            if !payload.is_empty() {
                payload.push('\n');
            }
            payload.push_str(data.trim());
        }
    }
    if !received {
        return Err("模型未返回文本或推理内容".into());
    }
    if !finished {
        return Err("模型数据流提前结束，已收到的内容已保留；可以继续对话".into());
    }
    Ok(())
}
fn stream_text(v: &Value) -> String {
    if let Some(t) = v.as_str() {
        return t.to_string();
    }
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|p| p["text"].as_str())
                .collect::<String>()
        })
        .unwrap_or_default()
}
fn split_thinking(raw: &str) -> (String, String) {
    let mut text = String::new();
    let mut thought = String::new();
    let mut remaining = raw;
    while let Some(start) = remaining.find("<think>") {
        text.push_str(&remaining[..start]);
        remaining = &remaining[start + 7..];
        if let Some(end) = remaining.find("</think>") {
            thought.push_str(&remaining[..end]);
            remaining = &remaining[end + 8..];
        } else {
            thought.push_str(remaining);
            remaining = "";
            break;
        }
    }
    // Do not briefly expose a fragmented opening tag during streaming.
    let cut = (1.."<think>".len())
        .rev()
        .find(|n| remaining.ends_with(&"<think>"[..*n]))
        .unwrap_or(0);
    text.push_str(&remaining[..remaining.len() - cut]);
    (text, thought)
}
// Bounded read-only subscriptions share the existing desktop channel / NDJSON transport.
fn qa_watch(root: &Path, a: &Value, emit: &mut impl FnMut(Value) -> R<()>) -> R<Value> {
    let _storage = storage_lock(root, false)?;
    let rid = s(a, "runId");
    if rid.len() != 32 || !rid.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)) {
        return Err("问答记录标识无效".into());
    }
    let mut path = project_dir(root, s(a, "project"))?;
    for part in ["qa", "runs", rid, "job.json"] {
        path.push(part);
        if path.is_symlink() { return Err("问答记录不支持符号链接".into()); }
    }
    let started = std::time::Instant::now();
    let mut heartbeat = started;
    let mut previous = Vec::new();
    loop {
        let bytes = fs::read(&path).map_err(err)?;
        if bytes != previous {
            let job: Value = serde_json::from_slice(&bytes).map_err(err)?;
            if job["id"] != rid { return Err("问答记录标识不一致".into()); }
            let terminal = !matches!(s(&job, "state"), "queued" | "running" | "stopping");
            emit(json!({"type":"qa_update", "data":job}))?;
            previous = bytes;
            heartbeat = std::time::Instant::now();
            if terminal { return Ok(json!({"terminal":true})); }
        }
        if started.elapsed().as_secs() >= 20 { return Ok(json!({"terminal":false})); }
        if heartbeat.elapsed().as_secs() >= 2 {
            emit(json!({"type":"heartbeat"}))?;
            heartbeat = std::time::Instant::now();
        }
        std::thread::sleep(std::time::Duration::from_millis(150));
    }
}
pub fn stream_dispatch(
    root: &Path,
    request: Value,
    mut emit: impl FnMut(Value) -> R<()>,
) -> R<Value> {
    if request["action"] == "qa.watch" { return qa_watch(root, &request["args"], &mut emit); }
    if request["action"] != "chat" {
        return Err("该操作不支持流式请求".into());
    }
    let _storage = storage_lock(root,false)?;
    let a = &request["args"];
    let c = db_project(root,s(a,"project"))?;
    valid_id(s(a, "streamId"))?;
    chat_stream(
        root,
        &c,
        s(a, "project"),
        s(a, "message"),
        s(a, "chatId"),
        s(a, "streamId"),
        a,
        &mut emit,
    )
}
fn chat_list(c: &Connection, p: &str) -> R<Value> {
    let mut st=c.prepare("SELECT id,name,parent_id,created FROM chat_threads WHERE project=? AND archived=0 ORDER BY rowid DESC").map_err(err)?;
    let result=st.query_map([p],|r|Ok(json!({"id":r.get::<_,String>(0)?,"name":r.get::<_,String>(1)?,"parentId":r.get::<_,Option<String>>(2)?,"created":r.get::<_,u64>(3)?}))).map_err(err)?.collect::<Result<Vec<_>,_>>().map_err(err)?;
    Ok(json!(result))
}
fn chat_get(c: &Connection, p: &str, id: &str) -> R<Value> {
    let (name, parent, data): (String, Option<String>, String) = c
        .query_row(
            "SELECT name,parent_id,data FROM chat_threads WHERE id=? AND project=? AND archived=0",
            params![id, p],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .map_err(|_| "对话不存在或已归档")?;
    Ok(
        json!({"id":id,"name":name,"parentId":parent,"messages":serde_json::from_str::<Value>(&data).map_err(err)?}),
    )
}
fn chat_lock(root: &Path, id: &str) -> R<std::fs::File> {
    valid_id(id)?;
    let lock = OpenOptions::new().create(true).truncate(false).read(true).write(true)
        .open(root.join(format!("data/research/chat-{id}.lock"))).map_err(err)?;
    lock.try_lock_exclusive().map_err(|_| "此对话正在生成回复，请先停止或等待完成")?;
    Ok(lock)
}
fn chat_stream(
    root: &Path,
    c: &Connection,
    p: &str,
    message: &str,
    chat_id: &str,
    stream_id: &str,
    model_selection: &Value,
    emit: &mut dyn FnMut(Value) -> R<()>,
) -> R<Value> {
    valid_id(p)?;
    if message.trim().is_empty() || message.chars().count() > 15000 {
        return Err("请输入 15000 字符以内的研究需求".into());
    }
    let owned_id = if chat_id.is_empty() {
        format!("legacy-{p}")
    } else {
        chat_id.to_string()
    };
    valid_id(&owned_id)?;
    if chat_id.is_empty() {
        c.execute(
            "INSERT OR IGNORE INTO chat_threads(id,project,name,data,created) VALUES(?,?,?,'[]',?)",
            params![owned_id, p, "新对话", now()],
        )
        .map_err(err)?;
    }
    let _lock = chat_lock(root, &owned_id)?;
    let thread = chat_get(c, p, &owned_id)?;
    let cfg = profile(c, model_selection)?;
    let mut history: Vec<Value> = thread["messages"].as_array().cloned().unwrap_or_default();
    let mesh_snapshot = setting(c, "mesh", Value::Null)?;
    let system="你是 ScholarNoteLM 的 PubMed 检索设计助手。用中文与用户讨论研究范围并设计检索式，不访问 PubMed、不试检索、不探索或猜测命中数，不声称已执行。根据需要澄清研究问题，给出一条宽范围基础检索及有价值的补充检索。同概念内 OR，必要概念间 AND，括号正确；自由词用 [tiab]，规范 MeSH 名称用 [MeSH Terms]。不要擅自添加日期或 JCR，它们由每条检索式单独配置。MeSH 名称将在本地索引核验，未确认的术语不要声称已核验。每条完整检索式放在单独的 ```pubmed 代码块内，并在其紧邻上方写 ### 检索式标题。代码块里只写检索式，解释放在代码块外。正常输出可读的 Markdown，不要用 JSON 包装回答。";
    let mut messages = vec![json!({"role":"system","content":system})];
    for m in history.iter().skip(history.len().saturating_sub(12)) {
        if !s(m, "text").trim().is_empty() {
            messages.push(json!({"role":m["role"],"content":m["text"]}));
        }
    }
    messages.push(json!({"role":"user","content":message}));
    history.push(json!({"role":"user","text":message,"created":now()}));
    let save = |items: &Vec<Value>| -> R<()> {
        c.execute(
            "UPDATE chat_threads SET data=? WHERE id=? AND project=?",
            params![serde_json::to_string(items).map_err(err)?, owned_id, p],
        )
        .map_err(err)?;
        Ok(())
    };
    save(&history)?;
    emit(json!({"type":"start"}))?;
    let (tx, rx) = std::sync::mpsc::sync_channel(32);
    let model = cfg["model"].clone();
    let model_label = format!("{}/{}", s(&cfg,"name"), s(&cfg,"model"));
    std::thread::spawn(move || {
        let r = llm_stream(&cfg, json!(messages), &mut |text, reasoning| {
            tx.send(json!({"type":"delta","text":text,"reasoning":reasoning}))
                .map_err(|_| "请求已停止".to_string())?;
            Ok(true)
        });
        let _ = tx.send(match r {
            Ok(()) => json!({"type":"end"}),
            Err(e) => json!({"type":"error","error":e}),
        });
    });
    let cancel = root.join(format!("data/research/cancel-{stream_id}"));
    let mut raw = String::new();
    let mut provider_reasoning = String::new();
    let mut failure = None;
    let mut cancelled = false;
    let mut dirty = false;
    let mut last_emit: Option<std::time::Instant> = None;
    let flush = |raw: &str, provider_reasoning: &str, emit: &mut dyn FnMut(Value) -> R<()>| -> R<()> {
        let (text, inline) = split_thinking(raw);
        let emitted_at=SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis() as u64;
        emit(json!({"type":"update","text":text,"reasoning":format!("{provider_reasoning}{inline}"),"emittedAt":emitted_at}))
    };
    loop {
        if !stream_id.is_empty() && cancel.exists() {
            cancelled = true;
            let _ = fs::remove_file(&cancel);
            break;
        }
        match rx.recv_timeout(Duration::from_millis(40)) {
            Ok(v) => match s(&v, "type") {
                "end" => break,
                "error" => {
                    failure = Some(s(&v, "error").to_string());
                    break;
                }
                _ => {
                    raw.push_str(s(&v, "text"));
                    provider_reasoning.push_str(s(&v, "reasoning"));
                    dirty = true;
                }
            },
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(_) => {
                failure = Some("模型连接意外结束，已收到的内容已保留".into());
                break;
            }
        }
        if dirty && last_emit.map_or(true,|at|at.elapsed()>=Duration::from_millis(40)) {
            if flush(&raw,&provider_reasoning,emit).is_err(){cancelled=true;break;}
            dirty=false;last_emit=Some(std::time::Instant::now());
        }
    }
    drop(rx);
    // Flush the tail on completion, cancellation and error without dropping tokens.
    if dirty { let _ = flush(&raw,&provider_reasoning,emit); }
    let (text, inline) = split_thinking(&raw);
    let reasoning = format!("{provider_reasoning}{inline}");
    let re = regex::Regex::new(r"(?ms)^```(?:pubmed|PubMed)\s*\n(.*?)^```[ \t]*").unwrap();
    let title_re = regex::Regex::new(r"(?m)^#{1,6}\s+(.+)$").unwrap();
    let mut queries = Vec::new();
    for cap in re.captures_iter(&text) {
        let query = cap[1].trim();
        if query.is_empty() {
            continue;
        }
        let title = title_re
            .captures_iter(&text[..cap.get(0).unwrap().start()])
            .last()
            .map(|c| c[1].to_string())
            .unwrap_or(format!("检索式 {}", queries.len() + 1));
        queries.push(json!({"id":uid(),"name":title,"text":query,"purpose":"","meshCheck":mesh_check_at(root,&mesh_snapshot,query).unwrap_or(json!([]))}));
    }
    history.push(json!({"role":"assistant","text":text,"reasoning":reasoning,"created":now(),"error":failure,"cancelled":cancelled,"result":{"queries":queries,"model":model,"modelLabel":model_label,"meshVersion":mesh_snapshot["version"]}}));
    save(&history)?;
    Ok(json!(history))
}
fn mesh_check_at(root: &Path, manifest: &Value, query: &str) -> R<Value> {
    let re =
        regex::Regex::new(r#"(?i)\"([^\"]+)\"\s*\[(?:mh|mesh|mesh terms)(?::noexp)?\]"#).unwrap();
    let mut result = Vec::new();
    for caps in re.captures_iter(query) {
        let term = &caps[1];
        let matches = mesh_lookup_at(root, manifest, term, 20)?;
        let matched = matches
            .as_array()
            .unwrap()
            .iter()
            .find(|x| x["kind"] == "descriptor" && s(x, "label").eq_ignore_ascii_case(term));
        result.push(json!({"term":term,"verified":matched.is_some(),"id":matched.map(|v|v["id"].clone()),"note":if matched.is_some(){"已核验规范名称"}else{"未在当前本地主词索引确认；请检查或改用自由词"}}));
    }
    Ok(json!(result))
}
pub fn project_dir(root: &Path, project: &str) -> R<std::path::PathBuf> {
    valid_id(project)?;
    let file=root.join("config/storage.json");
    let cfg:Value=if file.exists(){serde_json::from_slice(&fs::read(file).map_err(err)?).map_err(err)?}else{json!({})};
    if cfg["deletedProjects"].get(project).is_some(){return Err("项目已删除，请刷新项目列表".into());}
    let fallback:String=project.chars().filter(|c|c.is_ascii_alphanumeric()).collect();
    let folder=cfg["projects"][project].as_str().unwrap_or(&fallback);
    if folder.is_empty() || folder.chars().count()>64 || !folder.chars().all(|c|c.is_ascii_alphanumeric() || c=='_' || ('㐀'..='䶿').contains(&c) || ('一'..='鿿').contains(&c)) { return Err("项目文件夹名只能包含中文、英文字母、数字和下划线，长度 1–64".into()); }
    let upper=folder.to_ascii_uppercase();
    if ["CON","PRN","AUX","NUL"].contains(&upper.as_str()) || (upper.len()==4 && (upper.starts_with("COM") || upper.starts_with("LPT")) && upper.as_bytes()[3].is_ascii_digit()) {return Err("此文件夹名是 Windows 保留名称，请换一个".into());}
    let base=cfg["workspace"].as_str().map(std::path::PathBuf::from).unwrap_or_else(||root.join("workspace"));
    let dest=base.join(folder);
    if base.is_symlink() || dest.is_symlink(){return Err("工作目录不支持符号链接".into());}
    Ok(dest)
}
fn project_file(root:&Path,project:&str,value:&str)->R<std::path::PathBuf>{
    let base=project_dir(root,project)?;
    let path=Path::new(value);
    if path.is_absolute() || path.components().any(|c|matches!(c,std::path::Component::ParentDir)){return Err("项目文件路径无效".into());}
    // Compatibility for pre-migration run metadata, resolved in the new project root.
    let prefix=format!("data/projects/{project}/search/");
    Ok(base.join(value.strip_prefix(&prefix).map(|v|format!("pubmed/{v}")).unwrap_or_else(||value.to_string())))
}
fn storage_lock(root:&Path,exclusive:bool)->R<File>{
    fs::create_dir_all(root.join("config")).map_err(err)?;
    let f=OpenOptions::new().create(true).truncate(false).read(true).write(true).open(root.join("config/storage.lock")).map_err(err)?;
    let start=std::time::Instant::now();
    loop {
        let result=if exclusive {f.try_lock_exclusive()} else {FileExt::try_lock_shared(&f)};
        if result.is_ok(){break;}
        if start.elapsed()>Duration::from_secs(if exclusive{3}else{30}){return Err("项目正在使用，请等待检索、聊天或下载结束后再操作".into());}
        std::thread::sleep(Duration::from_millis(25));
    }
    Ok(f)
}
fn project_lock(root: &Path, p: &str) -> R<File> {
    valid_id(p)?;
    let f = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(root.join(format!("data/research/project-{p}.lock")))
        .map_err(err)?;
    f.lock_exclusive().map_err(err)?;
    Ok(f)
}
fn download_rpc(root: &Path, action: &str, mut args: Value) -> R<Value> {
    use std::process::{Command, Stdio};
    let runtime = if action.starts_with("vector.") { "marker" } else if action=="llm.test" && root.join(if cfg!(windows) {"runtimes/retrieval/Scripts/python.exe"} else {"runtimes/retrieval/bin/python"}).is_file() { "retrieval" } else { "downloader" };
    let python = root.join(if cfg!(windows) { format!("runtimes/{runtime}/Scripts/python.exe") } else { format!("runtimes/{runtime}/bin/python") });
    if !python.is_file() {
        return Err("下载运行时未安装，请运行 scripts/setup-downloader.py".into());
    }
    let owner = if std::env::current_exe()
        .ok()
        .and_then(|p| p.file_stem().map(|s| s.to_string_lossy().to_string()))
        .as_deref()
        == Some("scholarnotelm")
    {
        std::process::id()
    } else {
        0
    };
    args["owner"] = json!(owner);
    let mut command = Command::new(python);
    command
        .arg(root.join("services/downloader/engine.py"))
        .current_dir(root)
        .env("SCHOLARNOTELM_ROOT", root)
        .env("PYTHONUTF8", "1")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("TMPDIR", root.join("tmp"))
        .env("TEMP", root.join("tmp"))
        .env("TMP", root.join("tmp"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(err)?;
    child
        .stdin
        .take()
        .ok_or("无法打开下载进程")?
        .write_all(json!({"action":action,"args":args}).to_string().as_bytes())
        .map_err(err)?;
    if action=="zotero.pdf" {
        let cancel=project_dir(root,s(&args,"project"))?.join(format!("metadata/zotero-imports/{}/cancel",s(&args,"job")));
        let deadline=SystemTime::now()+Duration::from_secs(120);
        while child.try_wait().map_err(err)?.is_none(){
            if cancel.exists() || SystemTime::now()>deadline {
                let _=child.kill();let _=child.wait();
                if let Ok(base)=project_dir(root,s(&args,"project")){let _=fs::remove_file(base.join(format!("metadata/zotero-imports/{}/staging/{}.pdf",s(&args,"job"),s(&args,"pmid"))));}
                return Err(if cancel.exists(){"导入已取消"}else{"本地 PDF 处理超时，元数据已保留"}.into());
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    }
    let output = child.wait_with_output().map_err(err)?;
    let result: Value = serde_json::from_slice(&output.stdout)
        .map_err(|_| "下载服务异常退出，请检查本地运行时".to_string())?;
    if result["ok"] == true {
        Ok(result["data"].clone())
    } else {
        Err(s(&result, "error").to_string())
    }
}

pub fn dispatch(root: &Path, request: Value) -> R<Value> {
    let action = s(&request, "action");
    let a = &request["args"];
    let p = s(a, "project");
    if let Some(op)=action.strip_prefix("storage.") {
        let already_migrated=fs::read(root.join("config/storage.json")).ok().and_then(|b|serde_json::from_slice::<Value>(&b).ok()).is_some_and(|v|v["migrated"]==true && v["cleanupPending"]!=true);
        let _storage=storage_lock(root,op=="move" || op=="delete" || (op=="initialize" && !already_migrated))?;
        return download_rpc(root, &format!("storage.{op}"), if a.is_object(){a.clone()}else{json!({})});
    }
    let _storage=storage_lock(root,false)?;
    let mut c=if p.is_empty(){db(root)?}else{db_project(root,p)?};
    if action.starts_with("markdown.") || action.starts_with("vector.") || action.starts_with("review.") || action.starts_with("library.") || action.starts_with("qa.") {
        return download_rpc(root, action, if a.is_object(){a.clone()}else{json!({})});
    }
    if let Some(op) = action.strip_prefix("download.") {
        let mut args = if a.is_object() { a.clone() } else { json!({}) };
        let _download_guard=if ["start","import","export","clear","control"].contains(&op){Some(project_lock(root,p)?)}else{None};
        if ["start", "import", "export", "clear"].contains(&op) {
            valid_id(p)?;
            let current = corpus(root, &c, p)?;
            let papers: Vec<Value> = current["papers"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|v| v["included"] == true)
                .cloned()
                .collect();
            if op == "start" {
                let ids = a["pmids"].as_array();
                if let Some(ids) = ids {
                    if ids
                        .iter()
                        .any(|id| !papers.iter().any(|v| v["pmid"] == *id))
                    {
                        return Err("所选文献已不在当前纳入集合，请刷新后重试".into());
                    }
                }
                args["papers"] = json!(papers
                    .into_iter()
                    .filter(|v| ids.map_or(true, |ids| ids.contains(&v["pmid"])))
                    .collect::<Vec<_>>());
                args["snapshot"] = current["snapshot"].clone();
            } else if op == "import" {
                args["paper"] = papers
                    .into_iter()
                    .find(|v| v["pmid"] == a["pmid"])
                    .ok_or("只能给当前纳入的 PubMed 条目关联 PDF")?;
            } else {
                args["pmids"] = json!(papers.iter().map(|v| v["pmid"].clone()).collect::<Vec<_>>());
                args["snapshot"] = current["snapshot"].clone();
            }
        }
        return download_rpc(root, op, args);
    }
    // Take source ownership before the project write lock (the worker only needs
    // the latter). Holding it through query.run closes the start/commit race.
    let _source_operation=if ["zotero.start","query.run","query.save","query.create","query.filters.apply","query.toggle","query.archive","xml.import"].contains(&action){
        Some(zotero_import::source_operation(root,p)?)
    }else{None};
    let _lock = if !p.is_empty() && !["zotero.cancel", "zotero.status", "zotero.report", "zotero.collections", "zotero.preview", "query.run", "query.cancel", "chat", "chat.cancel"].contains(&action)
    {
        Some(project_lock(root, p)?)
    } else {
        None
    };
    if let Some(op)=action.strip_prefix("zotero."){return zotero_import::rpc(root,&mut c,p,op,a);}
    match action {
        "workspace" => workspace(root, &c, p),
        "query.save" | "query.create" => {
            valid_id(p)?;
            let text = s(a, "text").trim();
            if text.len() > 20000 {
                return Err("请输入有效检索式（最多 20000 字符）".into());
            }
            let name = if action == "query.create" {
                "未命名检索式"
            } else {
                s(a, "name").trim()
            };
            if name.is_empty() {
                return Err("请输入检索式名称".into());
            }
            let id = if s(a, "id").is_empty() {
                uid()
            } else {
                s(a, "id").to_string()
            };
            valid_id(&id)?;
            let source:Option<String>=c.query_row("SELECT source FROM queries WHERE id=? AND project=?",params![id,p],|r|r.get(0)).optional().map_err(err)?;
            if source.as_deref()==Some("zotero"){
                c.execute("UPDATE queries SET name=? WHERE id=? AND project=?",params![name,id,p]).map_err(err)?;
                return workspace(root,&c,p);
            }
            let f = if a["filters"].is_object() {
                a["filters"].clone()
            } else if s(a, "id").is_empty() {
                defaults()
            } else {
                query_filters(&c, &id)?
            };
            validate_filters(&f)?;
            let previous = query_filters(&c, &id)?;
            let search_changed = ["start", "end", "sort", "mode", "limit"]
                .iter()
                .any(|k| previous[k] != f[k]);
            let tx = c.transaction().map_err(err)?;
            if s(a, "id").is_empty() {
                tx.execute(
                    "INSERT INTO queries(id,project,name,text,source) VALUES(?,?,?,?,?)",
                    params![
                        id,
                        p,
                        name,
                        text,
                        if a["source"] == "assistant" {
                            "assistant"
                        } else {
                            "manual"
                        }
                    ],
                )
                .map_err(err)?;
            } else {
                let changed=tx.execute("UPDATE queries SET name=?,text=?,revision=revision+CASE WHEN text != ? OR ? THEN 1 ELSE 0 END,last_error='' WHERE id=? AND project=? AND revision=?",params![name,text,text,search_changed,id,p,a["revision"].as_u64().unwrap_or(0)]).map_err(err)?;
                if changed == 0 {
                    return Err("检索式已被其他操作更新，请刷新后再编辑".into());
                }
            }
            put(&tx, &format!("queryFilters:{id}"), &f)?;
            tx.commit().map_err(err)?;
            workspace(root, &c, p)
        }
        "query.filters.apply" => {
            valid_id(p)?;
            let dates = a["dates"].is_object();
            let jcr = a["jcr"].is_object();
            if !dates && !jcr { return Err("请选择要统一的筛选条件".into()); }
            // Only filter fields are accepted. Names, queries, limits and sort order stay independent.
            let mut probe = defaults();
            if dates { for key in ["start", "end"] { probe[key] = a["dates"][key].clone(); } }
            if jcr { for key in ["jcr", "quartiles", "unknown"] { probe[key] = a["jcr"][key].clone(); } }
            validate_filters(&probe)?;
            if dates && ["start", "end"].iter().any(|key| !probe[key].is_string()) {
                return Err("请提供有效的日期范围".into());
            }
            if jcr && (!probe["jcr"].is_boolean() || !probe["quartiles"].is_array() || !["keep", "exclude"].contains(&s(&probe,"unknown"))) {
                return Err("请提供有效的 JCR 筛选条件".into());
            }
            // Validate the reference before writing any query so failure cannot leave a partial batch.
            if probe["jcr"] == true {
                let reference = ensure_jcr(root, &c)?;
                if reference.is_null() { return Err("请先上传并校验 JCR 文件".into()); }
                Jcr::load(root, s(&reference,"version"))?;
            }
            let targets = {
                let mut stmt = c.prepare("SELECT id,source FROM queries WHERE project=? AND archived=0").map_err(err)?;
                let rows = stmt.query_map([p], |r| Ok((r.get::<_,String>(0)?, r.get::<_,String>(1)?))).map_err(err)?;
                rows.collect::<Result<Vec<_>,_>>().map_err(err)?
            };
            let tx = c.transaction().map_err(err)?;
            for (id, source) in targets {
                if source=="zotero" {continue;}
                let previous = query_filters(&tx, &id)?;
                let mut filters = previous.clone();
                // An imported XML has no executable PubMed query; its date range is immutable.
                if dates && source != "import" { for key in ["start", "end"] { filters[key] = probe[key].clone(); } }
                if jcr { for key in ["jcr", "quartiles", "unknown"] { filters[key] = probe[key].clone(); } }
                validate_filters(&filters)?;
                if filters != previous {
                    let search_changed = ["start", "end"].iter().any(|key| filters[key] != previous[key]);
                    tx.execute("UPDATE queries SET revision=revision+?,last_error='' WHERE id=? AND project=?", params![search_changed as i32,id,p]).map_err(err)?;
                    put(&tx, &format!("queryFilters:{id}"), &filters)?;
                }
            }
            tx.commit().map_err(err)?;
            workspace(root, &c, p)
        }
        "query.toggle" | "query.archive" => {
            valid_id(p)?;
            let field = if action == "query.toggle" {
                "enabled"
            } else {
                "archived"
            };
            c.execute(
                &format!("UPDATE queries SET {field}=? WHERE id=? AND project=?"),
                params![a["value"] == true, s(a, "id"), p],
            )
            .map_err(err)?;
            workspace(root, &c, p)
        }
        "query.run" => {
            valid_id(p)?;
            valid_id(s(a, "id"))?;
            let lock = OpenOptions::new()
                .create(true)
                .truncate(false)
                .read(true)
                .write(true)
                .open(root.join(format!("data/research/run-{}.lock", s(a, "id"))))
                .map_err(err)?;
            lock.try_lock_exclusive().map_err(|_| "此检索式正在执行")?;
            let execution_id = s(a,"executionId");
            let cancel = if execution_id.is_empty() { None } else {
                valid_id(execution_id)?;
                Some(root.join(format!("data/research/query-cancel-{p}-{}-{execution_id}",s(a,"id"))))
            };
            // Recheck on the backend so a stale batch plan cannot repeat a completed query.
            if a["onlyPending"] == true {
                let current = workspace(root,&c,p)?;
                let q = current["queries"].as_array().unwrap().iter().find(|q|q["id"]==a["id"]).ok_or("检索式不存在")?;
                if q["archived"]==true || q["enabled"]!=true || q["source"]=="import" || (q["xmlExists"]==true && q["stale"]!=true) { return Ok(current); }
            }
            let result = run_query(root, &mut c, p, s(a, "id"), cancel.as_deref(), a["force"]==true);
            if let Some(path) = &cancel { let _ = fs::remove_file(path); }
            if result.as_ref().err().is_some_and(|e|e==QUERY_CANCELLED) { return workspace(root,&c,p); }
            if let Err(e) = &result {
                c.execute(
                    "UPDATE queries SET last_error=? WHERE id=? AND project=?",
                    params![e, s(a, "id"), p],
                )
                .map_err(err)?;
            }
            result
        }
        "query.cancel" => {
            valid_id(p)?;valid_id(s(a,"id"))?;valid_id(s(a,"executionId"))?;
            // Serialize the stop request with final publication: completed results survive,
            // but a cancellation accepted before publication prevents any replacement.
            let _commit_lock = project_lock(root,p)?;
            write_file(&root.join(format!("data/research/query-cancel-{p}-{}-{}",s(a,"id"),s(a,"executionId"))),b"cancel")?;
            Ok(json!({"cancelled":true}))
        }
        "query.history" => {
            let mut st=c.prepare("SELECT r.data FROM runs r JOIN queries q ON q.id=r.query_id WHERE q.project=? AND q.id=? ORDER BY r.rowid DESC").map_err(err)?;
            let values = st
                .query_map(params![p, s(a, "id")], |r| r.get::<_, String>(0))
                .map_err(err)?
                .collect::<Result<Vec<_>, _>>()
                .map_err(err)?;
            Ok(json!(values
                .into_iter()
                .filter_map(|v| serde_json::from_str::<Value>(&v).ok())
                .collect::<Vec<_>>()))
        }
        "xml.import" => {
            valid_id(p)?;
            let articles = parse_pubmed(s(a, "xml"))?;
            if articles.is_empty() {
                return Err("XML 未包含有效 PubMed 文献记录".into());
            }
            let id = uid();
            let run = uid();
            let dir = project_dir(root,p)?.join(format!("pubmed/queries/{id}/runs/{run}"));
            write_file(&dir.join("raw.xml"), s(a, "xml").as_bytes())?;
            let data = json!({"id":run,"revision":1,"created":now(),"count":articles.len(),"fetched":articles.len(),"truncated":false,"filters":defaults(),"text":"导入批次：原始检索式未知","xmlPath":format!("pubmed/queries/{id}/runs/{run}/raw.xml")});
            let tx = c.transaction().map_err(err)?;
            tx.execute("INSERT INTO queries(id,project,name,text,source,active_run) VALUES(?,?,?,'','import',?)",params![id,p,s(a,"name"),run]).map_err(err)?;
            put(&tx, &format!("queryFilters:{id}"), &defaults())?;
            tx.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?)",
                params![run, id, 1, now(), data.to_string()],
            )
            .map_err(err)?;
            for (i, (pmid, v, xml)) in articles.iter().enumerate() {
                tx.execute(
                    "INSERT INTO articles VALUES(?,?,?) ON CONFLICT(pmid) DO NOTHING",
                    params![pmid, v.to_string(), xml],
                )
                .map_err(err)?;
                tx.execute(
                    "INSERT INTO members VALUES(?,?,?,?,?)",
                    params![run, pmid, i, v.to_string(), xml],
                )
                .map_err(err)?;
            }
            tx.commit().map_err(err)?;
            workspace(root, &c, p)
        }
        "xml.export" => {
            let path = if !s(a, "run").is_empty() {
                let data:String=c.query_row("SELECT r.data FROM runs r JOIN queries q ON q.id=r.query_id WHERE r.id=? AND q.project=?",params![s(a,"run"),p],|r|r.get(0)).map_err(err)?;
                let v: Value = serde_json::from_str(&data).map_err(err)?;
                project_file(root,p,s(&v,"xmlPath"))?
            } else {
                let result = corpus(root, &c, p)?;
                root.join(s(&result, "path"))
            };
            let content = fs::read_to_string(&path).map_err(err)?;
            let target = project_dir(root,p)?.join(format!("pubmed/exports/{}-pubmed.xml", uid()));
            write_file(&target, content.as_bytes())?;
            Ok(json!({"path":target.to_string_lossy(),"content":content}))
        }
        "settings" => {
            let profiles = setting(&c, "profiles", json!([]))?;
            let pubmed = setting(&c, "pubmed", json!({}))?;
            Ok(
                json!({"profiles":profiles.as_array().unwrap().iter().cloned().map(public_profile).collect::<Vec<_>>(),"activeProfile":setting(&c,"activeProfile",json!(""))?,"jcr":ensure_jcr(root,&c)?,"mesh":mesh_status(root,&c)?,"pubmed":{"email":pubmed["email"],"hasKey":!s(&pubmed,"apiKey").is_empty()}}),
            )
        }
        "profile.list" => {
            let profiles = setting(&c, "profiles", json!([]))?;
            Ok(json!({"profiles":profiles.as_array().unwrap().iter().cloned().map(public_profile).collect::<Vec<_>>(),"activeProfile":setting(&c,"activeProfile",json!(""))?}))
        }
        "profile.key" => {
            valid_id(s(a, "id"))?;
            let profiles = setting(&c, "profiles", json!([]))?;
            let saved = profiles.as_array().unwrap().iter().find(|p| p["id"] == a["id"]).ok_or("配置不存在")?;
            Ok(json!({"apiKey":s(saved,"apiKey")}))
        }
        "profile.save" => {
            let tx=c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(err)?;
            let mut value = profile(&tx, a)?;
            for field in ["name", "baseUrl", "model", "apiKey"] {
                value[field] = json!(s(&value, field).trim());
            }
            let mut selected: Vec<String> = Vec::new();
            if let Some(models) = value.get("models") {
                for model in models.as_array().ok_or("模型列表格式无效")? {
                    let name = model.as_str().ok_or("模型名称必须是文本")?.trim();
                    if name.is_empty() || name.len() > 500 || name.chars().any(char::is_control) { return Err("模型名称无效".into()); }
                    if !selected.iter().any(|m| m == name) { selected.push(name.into()); }
                }
            }
            let default_model = s(&value,"model").to_string();
            if !default_model.is_empty() && !selected.contains(&default_model) { selected.push(default_model); }
            if s(&value,"model").is_empty() && !selected.is_empty() { value["model"] = json!(selected[0]); }
            value["models"] = json!(selected);
            let models_url = llm_url(&value, "models")?;
            value["baseUrl"] = json!(models_url.strip_suffix("/models").unwrap_or(&models_url));
            if s(&value, "name").trim().is_empty() {
                return Err("请填写配置名称".into());
            }
            if s(&value, "id").is_empty() {
                value["id"] = json!(uid());
            }
            valid_id(s(&value, "id"))?;
            if !(10..=600).contains(&value["timeout"].as_u64().unwrap_or(120))
                || (!value["temperature"].is_null()
                    && !value["temperature"]
                        .as_f64()
                        .is_some_and(|v| (0.0..=2.0).contains(&v)))
            {
                return Err("超时应为 10–600 秒，温度应为 0–2 或留空".into());
            }
            let mut profiles = setting(&tx, "profiles", json!([]))?;
            if profiles.as_array().unwrap().iter().any(|p| p["id"] != value["id"] && s(p,"name").to_lowercase() == s(&value,"name").to_lowercase()) { return Err("配置名称已存在，请使用不同名称".into()); }
            // Action flags belong to this request, not the persisted profile.
            if let Some(o) = value.as_object_mut() { o.remove("hasKey"); o.remove("clearKey"); }
            let arr = profiles.as_array_mut().unwrap();
            arr.retain(|p| p["id"] != value["id"]);
            arr.push(value.clone());
            put(&tx, "profiles", &profiles)?;
            let active = setting(&tx,"activeProfile",json!(""))?;
            let has_default=profiles.as_array().unwrap().iter().any(|p| p["id"]==active && !s(p,"model").is_empty());
            if a["makeDefault"]==true && !s(&value,"model").is_empty() {
                put(&tx,"activeProfile",&value["id"])?;
            } else if !has_default {
                let fallback=profiles.as_array().unwrap().iter().find(|p| !s(p,"model").is_empty()).map(|p| p["id"].clone()).unwrap_or(json!(""));
                put(&tx,"activeProfile",&fallback)?;
            }
            tx.commit().map_err(err)?;
            Ok(public_profile(value))
        }

        "profile.delete" => {
            let tx=c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(err)?;
            let mut profiles = setting(&tx, "profiles", json!([]))?;
            profiles
                .as_array_mut()
                .unwrap()
                .retain(|v| v["id"] != a["id"]);
            put(&tx, "profiles", &profiles)?;
            if setting(&tx, "activeProfile", Value::Null)? == a["id"] {
                let fallback=profiles.as_array().unwrap().iter().find(|p| !s(p,"model").is_empty()).map(|p| p["id"].clone()).unwrap_or(json!(""));
                put(&tx, "activeProfile", &fallback)?;
            }
            tx.commit().map_err(err)?;
            Ok(json!(true))
        }
        "llm.models" => {
            let cfg = profile(&c, a)?;
            let mut req = model_client(30)?.get(llm_url(&cfg, "models")?);
            if !s(&cfg, "apiKey").is_empty() {
                req = req.bearer_auth(s(&cfg, "apiKey"));
            }
            let response = req.send().map_err(|_| "模型列表连接失败")?;
            if !response.status().is_success() {
                return Err(format!(
                    "获取模型列表失败（HTTP {}），仍可手动填写模型名",
                    response.status()
                ));
            }
            let v: Value = response.json().map_err(err)?;
            let models: Vec<_> = v["data"]
                .as_array()
                .ok_or("接口未返回 data 模型列表")?
                .iter()
                .filter_map(|m| m["id"].as_str())
                .collect();
            Ok(json!(models))
        }
        "llm.test" => {
            let cfg = profile(&c, a)?;
            download_rpc(root, "llm.test", json!({"profile":cfg}))
        }
        "pubmed.key" => {
            let cfg=setting(&c,"pubmed",json!({}))?;
            Ok(json!({"apiKey":s(&cfg,"apiKey")}))
        }
        "pubmed.save" => {
            let mut cfg = setting(&c, "pubmed", json!({}))?;
            cfg["email"] = a["email"].clone();
            if !s(a, "apiKey").is_empty() {
                cfg["apiKey"] = a["apiKey"].clone();
            }
            if a["clearKey"] == true {
                cfg["apiKey"] = json!("");
            }
            put(&c, "pubmed", &cfg)?;
            Ok(json!(true))
        }
        "jcr.upload" => {
            let name = s(a, "name");
            let ext = Path::new(name)
                .extension()
                .and_then(|x| x.to_str())
                .unwrap_or("")
                .to_lowercase();
            if !["xls", "xlsx"].contains(&ext.as_str()) {
                return Err("仅支持 .xls / .xlsx".into());
            }
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(s(a, "base64"))
                .map_err(|_| "文件内容无效")?;
            if bytes.len() > 30_000_000 {
                return Err("JCR 文件不能大于 30 MB".into());
            }
            let temp = root.join(format!("tmp/jcr-{}.{}", uid(), ext));
            write_file(&temp, &bytes)?;
            let result = activate_jcr(root, &c, &temp, name);
            let _ = fs::remove_file(temp);
            result
        }
        "jcr.validate" => {
            let j = ensure_jcr(root, &c)?;
            let version = s(&j, "version");
            let dir = root.join("data/reference/jcr");
            let path = [
                dir.join(format!("{version}.xlsx")),
                dir.join(format!("{version}.xls")),
            ]
            .into_iter()
            .find(|p| p.exists())
            .ok_or("当前 JCR 文件缺失")?;
            let mut report = jcr_validate(&path)?;
            report.as_object_mut().unwrap().remove("records");
            Ok(report)
        }
        "jcr.default" => activate_jcr(
            root,
            &c,
            &root.join("data/reference/jcr/default-2025.xlsx"),
            "BADR · 2025JCR.xlsx",
        ),
        "mesh.search" => mesh_lookup(root, &c, s(a, "query"), 20),
        "mesh.status" => mesh_status(root, &c),
        "mesh.update" => update_mesh(root, a["force"] == true),
        "mesh.settings" => {
            put(&c, "meshAuto", &json!(a["autoUpdate"] == true))?;
            put(&c, "meshScr", &json!(a["includeScr"] == true))?;
            Ok(json!(true))
        }
        "chat.list" => chat_list(&c, p),
        "chat.get" => chat_get(&c, p, s(a, "id")),
        "chat.new" | "chat.fork" | "chat.copy" => {
            valid_id(p)?;
            let _copy_lock = if action == "chat.copy" { Some(chat_lock(root, s(a, "id"))?) } else { None };
            let id = uid();
            let mut messages = json!([]);
            let mut parent = Value::Null;
            let mut name = if s(a, "name").trim().is_empty() {
                "新对话".to_string()
            } else {
                s(a, "name").chars().take(80).collect()
            };
            if action == "chat.copy" {
                let old = chat_get(&c, p, s(a, "id"))?;
                messages = old["messages"].clone();
                name = format!("副本 · {}", s(&old, "name").chars().take(75).collect::<String>());
            }
            if action == "chat.fork" {
                let old = chat_get(&c, p, s(a, "id"))?;
                let all = old["messages"].as_array().unwrap();
                let count = a["keepCount"].as_u64().ok_or("请选择分支位置")? as usize;
                if count > all.len() {
                    return Err("分支位置无效".into());
                }
                messages = json!(&all[..count]);
                parent = a["id"].clone();
                let count: u32 = c
                    .query_row(
                        "SELECT COUNT(*) FROM chat_threads WHERE project=? AND parent_id=?",
                        params![p, s(a, "id")],
                        |r| r.get(0),
                    )
                    .map_err(err)?;
                name = format!(
                    "分支 {} · {}",
                    count + 1,
                    s(&old, "name").chars().take(55).collect::<String>()
                );
            }
            c.execute("INSERT INTO chat_threads(id,project,name,parent_id,data,created) VALUES(?,?,?,?,?,?)",params![id,p,name,parent.as_str(),messages.to_string(),now()]).map_err(err)?;
            chat_get(&c, p, &id)
        }
        "chat.archive_many" => {
            let ids = a["ids"].as_array().filter(|ids| !ids.is_empty()).ok_or("请选择要删除的对话")?;
            let mut unique_ids = std::collections::BTreeSet::new();
            for id in ids { unique_ids.insert(id.as_str().ok_or("对话编号无效")?); }
            let _locks = unique_ids.iter().map(|id| chat_lock(root, id)).collect::<R<Vec<_>>>()?;
            let tx = c.unchecked_transaction().map_err(err)?;
            // All targets must belong to this project and still be visible.
            for id in ids {
                chat_get(&tx, p, id.as_str().ok_or("对话编号无效")?)?;
            }
            for id in ids {
                tx.execute("UPDATE chat_threads SET archived=1 WHERE id=? AND project=?", params![id.as_str().unwrap(), p]).map_err(err)?;
            }
            tx.commit().map_err(err)?;
            chat_list(&c, p)
        }
        "chat.rename" | "chat.archive" => {
            let _archive_lock = if action == "chat.archive" { Some(chat_lock(root, s(a, "id"))?) } else { None };
            chat_get(&c, p, s(a, "id"))?;
            if action == "chat.rename" {
                if s(a, "name").trim().is_empty() {
                    return Err("请填写对话名称".into());
                }
                c.execute(
                    "UPDATE chat_threads SET name=? WHERE id=? AND project=?",
                    params![
                        s(a, "name").chars().take(80).collect::<String>(),
                        s(a, "id"),
                        p
                    ],
                )
                .map_err(err)?;
            } else {
                c.execute(
                    "UPDATE chat_threads SET archived=1 WHERE id=? AND project=?",
                    params![s(a, "id"), p],
                )
                .map_err(err)?;
            }
            chat_list(&c, p)
        }
        "chat" => chat_stream(
            root,
            &c,
            p,
            s(a, "message"),
            s(a, "chatId"),
            "",
            a,
            &mut |_| Ok(()),
        ),
        "chat.cancel" => {
            valid_id(s(a, "streamId"))?;
            write_file(
                &root.join(format!("data/research/cancel-{}", s(a, "streamId"))),
                b"cancel",
            )?;
            Ok(json!(true))
        }
        _ => Err("未知研究操作".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn temp() -> PathBuf {
        let p = std::env::temp_dir().join(format!("scholarnotelm-test-{}", uid()));
        fs::create_dir_all(&p).unwrap();
        p
    }
    use std::path::PathBuf;
    #[test]
    fn model_pool_default_and_workspace_selection_are_independent() {
        let root=temp();
        let save=|id:&str, model:&str, make_default:bool| dispatch(&root,json!({"action":"profile.save","args":{"makeDefault":make_default,"profile":{"id":id,"name":id,"baseUrl":"http://127.0.0.1:9999/v1","models":["one","two"],"model":model,"apiKey":"fixture-key","temperature":null,"timeout":120}}})).unwrap();
        save("provider-a","one",false);
        save("provider-b","one",false);
        let c=db(&root).unwrap();
        assert_eq!(setting(&c,"activeProfile",Value::Null).unwrap(),"provider-a");
        let selected=profile(&c,&json!({"profileId":"provider-b","model":"two"})).unwrap();
        assert_eq!(selected["id"],"provider-b");assert_eq!(selected["model"],"two");
        assert_eq!(selected["apiKey"],"fixture-key");
        assert_eq!(profile(&c,&json!({})).unwrap()["model"],"one");
        assert!(profile(&c,&json!({"profileId":"provider-b","model":"removed"})).is_err());
        save("provider-b","two",true);
        assert_eq!(setting(&c,"activeProfile",Value::Null).unwrap(),"provider-b");
        assert_eq!(profile(&c,&json!({})).unwrap()["model"],"two");
        save("provider-a","two",false);
        assert_eq!(setting(&c,"activeProfile",Value::Null).unwrap(),"provider-b");
        // Clearing the default's pool falls back to another configured model.
        dispatch(&root,json!({"action":"profile.save","args":{"profile":{"id":"provider-b","name":"provider-b","baseUrl":"http://127.0.0.1:9999/v1","models":[],"model":"","temperature":null,"timeout":120}}})).unwrap();
        assert_eq!(setting(&c,"activeProfile",Value::Null).unwrap(),"provider-a");
        dispatch(&root,json!({"action":"profile.delete","args":{"id":"provider-a"}})).unwrap();
        assert_eq!(setting(&c,"activeProfile",Value::Null).unwrap(),"");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn search_stream_sends_the_workspace_model_to_provider() {
        use std::net::TcpListener;
        let root=temp();let listener=TcpListener::bind("127.0.0.1:0").unwrap();
        let address=listener.local_addr().unwrap();
        let server=std::thread::spawn(move || {
            let (mut socket,_)=listener.accept().unwrap();
            socket.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
            let mut reader=BufReader::new(socket.try_clone().unwrap());let mut length=0;
            loop {let mut line=String::new();reader.read_line(&mut line).unwrap();if line=="\r\n"{break;}if let Some(v)=line.to_lowercase().strip_prefix("content-length:"){length=v.trim().parse::<usize>().unwrap();}}
            let mut body=vec![0;length];reader.read_exact(&mut body).unwrap();
            let request:Value=serde_json::from_slice(&body).unwrap();
            let response="data: {\"choices\":[{\"delta\":{\"content\":\"fixture response\"}}]}\n\ndata: [DONE]\n\n";
            write!(socket,"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",response.len(),response).unwrap();
            request
        });
        dispatch(&root,json!({"action":"profile.save","args":{"profile":{"id":"provider","name":"Fixture","baseUrl":format!("http://{address}/v1"),"models":["default-model","workspace-model"],"model":"default-model","temperature":null,"timeout":10}}})).unwrap();
        let thread=dispatch(&root,json!({"action":"chat.new","args":{"project":"test"}})).unwrap();
        let result=stream_dispatch(&root,json!({"action":"chat","args":{"project":"test","chatId":thread["id"],"streamId":"fixture-stream","message":"test","profileId":"provider","model":"workspace-model"}}),|_|Ok(())).unwrap();
        let request=server.join().unwrap();assert_eq!(request["model"],"workspace-model");
        assert_eq!(result[1]["text"],"fixture response");assert_eq!(result[1]["result"]["model"],"workspace-model");
        assert_eq!(profile(&db(&root).unwrap(),&json!({})).unwrap()["model"],"default-model");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn qa_watch_validates_run_and_streams_terminal_snapshot() {
        let root = temp();
        let rid = "a".repeat(32);
        let path = project_dir(&root,"test").unwrap().join("qa/runs").join(&rid);
        fs::create_dir_all(&path).unwrap();
        fs::write(path.join("job.json"),json!({"id":rid,"state":"done","events":[{"type":"tool","action":{"tool":"exact","text":"neutrophil"}}]}).to_string()).unwrap();
        let mut events=Vec::new();
        let result=stream_dispatch(&root,json!({"action":"qa.watch","args":{"project":"test","runId":rid}}),|v|{events.push(v);Ok(())}).unwrap();
        assert_eq!(result["terminal"],true);
        assert_eq!(events.len(),1);
        assert_eq!(events[0]["data"]["events"][0]["action"]["text"],"neutrophil");
        for bad in ["../other","ABC","", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"] {
            assert!(qa_watch(&root,&json!({"project":"test","runId":bad}),&mut |_|Ok(())).is_err());
        }
        fs::write(path.join("job.json"),json!({"id":rid,"state":"running"}).to_string()).unwrap();
        assert_eq!(qa_watch(&root,&json!({"project":"test","runId":rid}),&mut |_|Err("disconnected".into())).unwrap_err(),"disconnected");
        fs::remove_dir_all(root).unwrap();
    }
    #[cfg(unix)]
    #[test]
    fn qa_watch_rejects_symlinked_run() {
        let root=temp();let project=project_dir(&root,"test").unwrap();
        fs::create_dir_all(&project).unwrap();
        std::os::unix::fs::symlink(&root,project.join("qa")).unwrap();
        assert!(qa_watch(&root,&json!({"project":"test","runId":"a".repeat(32)}),&mut |_|Ok(())).unwrap_err().contains("符号链接"));
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn pubmed_identity_and_nested_text() {
        let xml = r#"<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Role of <i>microglia</i></ArticleTitle><Abstract><AbstractText Label="RESULTS">A &amp; B</AbstractText></Abstract><Journal><Title>Test Journal</Title><ISSN>1234-5678</ISSN><JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/own</ArticleId></ArticleIdList><ReferenceList><Reference><ArticleIdList><ArticleId IdType="pubmed">999</ArticleId><ArticleId IdType="doi">10.1/cited</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>"#;
        let a = parse_pubmed(xml).unwrap();
        assert_eq!(a[0].0, "123");
        assert_eq!(a[0].1["title"], "Role of microglia");
        assert_eq!(a[0].1["doi"], "10.1/own");
        assert_eq!(a[0].1["abstract"], "RESULTS: A & B");
    }
    #[test]
    fn invalid_identity_rejected() {
        assert!(parse_pubmed("<PubmedArticleSet><PubmedArticle><MedlineCitation><Article/></MedlineCitation></PubmedArticle></PubmedArticleSet>").is_err());
    }
    #[test]
    fn pubmed_book_chapters_preserve_identity_and_original_xml() {
        let xml = include_str!("../../../../services/downloader/tests/fixtures/pubmed-book.xml");
        let a = parse_pubmed(xml).unwrap();
        assert_eq!(a.len(), 2);
        assert_eq!(a[1].0, "456");
        assert_eq!(a[1].1["title"], "Genetic conditions");
        assert_eq!(a[1].1["author"], "Writer W");
        assert_eq!(a[1].1["journal"], "Reference book");
        assert_eq!(a[1].1["year"], 2008);
        assert_eq!(a[1].1["doi"], "10.1234/chapter");
        assert_eq!(a[1].1["pmcid"], "");
        assert_eq!(a[1].1["recordType"], "book_chapter");
        assert!(a[1].1["abstract"].as_str().unwrap().starts_with("BACKGROUND: Chapter abstract"));
        assert!(a[1].2.starts_with("<PubmedBookArticle>"));
        assert_eq!(parse_pubmed(&pack_xml(&a.iter().map(|x|x.2.clone()).collect::<Vec<_>>())).unwrap().len(),2);
        assert!(parse_pubmed(&xml.replace("<PMID>456</PMID>", "")).is_err());
    }
    #[test]
    fn mesh_index_synonyms() {
        let root = temp();
        let path = root.join("mesh.xml");
        fs::write(&path,r#"<DescriptorRecordSet><DescriptorRecord><DescriptorUI>D008822</DescriptorUI><DescriptorName><String>Microglia</String></DescriptorName><TreeNumberList><TreeNumber>A11.118</TreeNumber></TreeNumberList><ConceptList><Concept><ScopeNote>Brain immune cells.</ScopeNote><TermList><Term><String>Microglial Cells</String></Term></TermList></Concept></ConceptList></DescriptorRecord></DescriptorRecordSet>"#).unwrap();
        let mut c = Connection::open(root.join("mesh.db")).unwrap();
        c.execute_batch("CREATE TABLE descriptors(id TEXT PRIMARY KEY,data TEXT);CREATE VIRTUAL TABLE terms USING fts5(id UNINDEXED,label,synonyms);").unwrap();
        assert_eq!(
            index_mesh_file(&mut c, &path, "descriptor").unwrap(),
            (1, 1)
        );
        let id: String = c
            .query_row(
                "SELECT id FROM terms WHERE terms MATCH 'Microglial'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(id, "D008822");
        drop(c);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn union_archive_draft_and_snapshot() {
        let root = temp();
        let call = |action: &str, args: Value| {
            dispatch(&root, json!({"action":action,"args":args})).unwrap()
        };
        let xml = |ids: &[u32]| {
            format!("<PubmedArticleSet>{}</PubmedArticleSet>",ids.iter().map(|id|format!("<PubmedArticle><MedlineCitation><PMID>{id}</PMID><Article><ArticleTitle>Paper {id}</ArticleTitle><Abstract><AbstractText>Evidence.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>")).collect::<Vec<_>>().join(""))
        };
        let a = call(
            "xml.import",
            json!({"project":"test","name":"A","xml":xml(&[101,102,103])}),
        );
        let aid = a["queries"][0]["id"].clone();
        let b = call(
            "xml.import",
            json!({"project":"test","name":"B","xml":xml(&[103,104])}),
        );
        assert_eq!(b["corpus"]["included"], 4);
        let snap = b["corpus"]["snapshot"].as_str().unwrap();
        let d = call(
            "query.archive",
            json!({"project":"test","id":aid,"value":true}),
        );
        assert_eq!(d["corpus"]["included"], 2);
        let ids: Vec<_> = d["corpus"]["papers"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| s(v, "pmid"))
            .collect();
        assert_eq!(ids, vec!["103", "104"]);
        assert!(root
            .join(format!(
                "workspace/test/pubmed/snapshots/{snap}/pubmed.xml"
            ))
            .exists());
        let restored = call(
            "query.archive",
            json!({"project":"test","id":aid,"value":false}),
        );
        assert_eq!(restored["corpus"]["included"], 4);
        let saved = call(
            "query.save",
            json!({"project":"test","name":"Unexecuted","text":"microglia[tiab]"}),
        );
        assert_eq!(saved["corpus"]["included"], 4);
        let current=root.join("workspace/test/pubmed/current.xml");
        let modified=fs::metadata(&current).unwrap().modified().unwrap();
        call("workspace",json!({"project":"test"}));
        assert_eq!(fs::metadata(&current).unwrap().modified().unwrap(),modified);
        fs::remove_file(&current).unwrap();
        call("workspace",json!({"project":"test"}));
        assert!(current.is_file());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn url_keeps_provider_path() {
        assert_eq!(
            llm_url(&json!({"baseUrl":"https://example.com/api/v4"}), "models").unwrap(),
            "https://example.com/api/v4/models"
        );
        assert_eq!(
            llm_url(&json!({"baseUrl":"http://127.0.0.1:11434/v1"}), "models").unwrap(),
            "http://127.0.0.1:11434/v1/models"
        );
        assert!(llm_url(&json!({"baseUrl":"https://secret@example.com"}), "models").is_err());
    }
    #[test]
    fn unknown_fields_and_unbalanced_syntax_rejected() {
        assert!(validate_query("microglia[not_a_real_field]").is_err());
        assert!(validate_query("(microglia[tiab]").is_err());
        assert!(validate_query("\"cell death\"[tiab:~3] AND \"Microglia\"[mh:noexp]").is_ok());
        assert!(validate_query("\"[18F] imaging\"[Title]").is_ok());
    }
    #[test]
    fn mesh_nested_qualifier_and_whitespace() {
        let v=mesh_record("<DescriptorRecord><DescriptorUI>D017628</DescriptorUI><DescriptorName>\n  <String>Microglia</String>\n</DescriptorName><AllowableQualifiersList><AllowableQualifier><QualifierReferredTo><QualifierUI>Q000276</QualifierUI><QualifierName>\n<String>immunology</String>\n</QualifierName></QualifierReferredTo></AllowableQualifier></AllowableQualifiersList></DescriptorRecord>","descriptor").unwrap();
        assert_eq!(v["label"], "Microglia");
        assert_eq!(v["qualifiers"][0]["id"], "Q000276");
        assert_eq!(v["qualifiers"][0]["label"], "immunology");
    }
    #[test]
    fn filters_validate_dates() {
        let mut f = defaults();
        f["start"] = json!("2025-02-31");
        assert!(validate_filters(&f).is_err());
        f["start"] = json!("2025-02-01");
        f["end"] = json!("2024-01-01");
        assert!(validate_filters(&f).is_err());
    }
    #[test]
    fn bulk_filters_preserve_query_settings_and_allow_individual_overrides() {
        let root=temp();
        let call=|action:&str,args:Value| dispatch(&root,json!({"action":action,"args":args})).unwrap();
        let xml="<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>101</PMID><Article><ArticleTitle>One</ArticleTitle><Journal><Title>Journal A</Title></Journal><Abstract><AbstractText>Evidence.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle><PubmedArticle><MedlineCitation><PMID>102</PMID><Article><ArticleTitle>Two</ArticleTitle><Journal><Title>Journal B</Title></Journal><Abstract><AbstractText>Evidence.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>";
        let first=call("xml.import",json!({"project":"test","name":"Search","xml":xml}));
        let id=first["queries"][0]["id"].clone();
        call("xml.import",json!({"project":"test","name":"Imported","xml":xml}));
        call("query.save",json!({"project":"test","name":"Disabled","text":"kidney[tiab]"}));
        call("query.save",json!({"project":"test","name":"Archived","text":"kidney[tiab]"}));
        call("query.save",json!({"project":"other","name":"Other project","text":"kidney[tiab]"}));
        let c=db_project(&root,"test").unwrap();
        c.execute("UPDATE queries SET source='manual' WHERE id=?",[id.as_str().unwrap()]).unwrap();
        c.execute("UPDATE queries SET enabled=0 WHERE name='Disabled'",[]).unwrap();
        c.execute("UPDATE queries SET archived=1 WHERE name='Archived'",[]).unwrap();
        let mut f=defaults();f["limit"]=json!(77);f["sort"]=json!("pub_date");
        put(&c,&format!("queryFilters:{}",id.as_str().unwrap()),&f).unwrap();
        let patch=json!({"project":"test","dates":{"start":"2020-01-01","end":"2026-09-29"},"jcr":{"jcr":true,"quartiles":["Q1"],"unknown":"exclude"}});
        // A missing reference must not partially save dates before failing.
        assert!(dispatch(&root,json!({"action":"query.filters.apply","args":patch})).is_err());
        assert_eq!(query_filters(&c,id.as_str().unwrap()).unwrap(),f);
        write_file(&root.join("data/reference/jcr/fixture.json"),json!([{"journal":"Journal A","quartile":"Q1"},{"journal":"Journal B","quartile":"Q2"}]).to_string().as_bytes()).unwrap();
        put(&c,"jcr",&json!({"version":"fixture"})).unwrap();drop(c);
        let applied=call("query.filters.apply",patch);
        assert_eq!(applied["corpus"]["included"],1);
        let by_name=|name:&str| applied["queries"].as_array().unwrap().iter().find(|q|q["name"]==name).unwrap();
        assert_eq!(by_name("Search")["filters"]["limit"],77);
        assert_eq!(by_name("Search")["filters"]["sort"],"pub_date");
        assert_eq!(by_name("Search")["stale"],true);
        assert_eq!(by_name("Search")["revision"],2);
        assert_eq!(by_name("Disabled")["filters"]["start"],"2020-01-01");
        assert_eq!(by_name("Disabled")["enabled"],false);
        assert_eq!(by_name("Imported")["filters"]["start"],"");
        assert_eq!(by_name("Imported")["filters"]["quartiles"],json!(["Q1"]));
        assert_eq!(by_name("Imported")["stale"],false);
        assert_eq!(by_name("Archived")["filters"],defaults());
        let other=call("workspace",json!({"project":"other"}));assert_eq!(other["queries"][0]["filters"],defaults());
        let mut one=by_name("Search").clone();one["project"]=json!("test");one["filters"]["quartiles"]=json!(["Q1","Q2"]);
        let overridden=call("query.save",one);assert_eq!(overridden["corpus"]["included"],2);
        for q in overridden["queries"].as_array().unwrap().iter().filter(|q|q["name"]=="Disabled"||q["name"]=="Imported") { assert_eq!(q["filters"]["quartiles"],json!(["Q1"])); }
        let before=overridden["queries"].clone();
        assert!(dispatch(&root,json!({"action":"query.filters.apply","args":{"project":"test","dates":{"start":"2026-01-01","end":"2020-01-01"}}})).is_err());
        assert_eq!(call("workspace",json!({"project":"test"}))["queries"],before);
        let dates_only=call("query.filters.apply",json!({"project":"test","dates":{"start":"","end":""}}));
        let search=dates_only["queries"].as_array().unwrap().iter().find(|q|q["id"]==id).unwrap();
        assert_eq!(search["filters"]["quartiles"],json!(["Q1","Q2"]));
        assert_eq!(search["filters"]["start"],"");
        let reset=call("query.filters.apply",json!({"project":"test","jcr":{"jcr":false,"quartiles":[],"unknown":"keep"}}));
        assert_eq!(reset["corpus"]["included"],2);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn query_pending_tracks_selection_conditions_and_policy() {
        let f=defaults();let run=json!({"selectionPolicy":SELECTION_POLICY,"text":"kidney[tiab]","revision":1,"filters":f});
        assert!(!query_fetch_stale(&run,"kidney[tiab]",&f));
        let mut local=f.clone();local["jcr"]=json!(true);local["quartiles"]=json!(["Q1"]);local["unknown"]=json!("exclude");
        assert!(query_fetch_stale(&run,"kidney[tiab]",&local));
        for (key,value) in [("start",json!("2025-01-01")),("end",json!("2025-12-31")),("limit",json!(60)),("sort",json!("pub_date")),("mode",json!("full"))] {
            let mut changed=f.clone();changed[key]=value;assert!(query_fetch_stale(&run,"kidney[tiab]",&changed),"{key}");
        }
        assert!(query_fetch_stale(&run,"kidney[tiab] AND immunity[tiab]",&f));
        assert!(!query_fetch_stale(&run,"kidney[tiab]",&f));
    }
    #[test]
    fn pending_run_skips_current_xml_and_cancel_preserves_old_run() {
        let root=temp();let project="test";
        let saved=dispatch(&root,json!({"action":"query.save","args":{"project":project,"name":"Query","text":"kidney[tiab]"}})).unwrap();
        let id=s(&saved["queries"][0],"id").to_string();let c=db_project(&root,project).unwrap();
        let xml_path=format!("pubmed/queries/{id}/runs/old/raw.xml");
        let run=json!({"selectionPolicy":SELECTION_POLICY,"id":"old","revision":1,"text":"kidney[tiab]","filters":defaults(),"xmlPath":xml_path,"created":1,"count":0,"fetched":0});
        let old_xml=project_file(&root,project,&xml_path).unwrap();write_file(&old_xml,b"<PubmedArticleSet/>").unwrap();
        c.execute("INSERT INTO runs VALUES('old',?,1,1,?)",params![id,run.to_string()]).unwrap();
        c.execute("UPDATE queries SET active_run='old' WHERE id=?",[&id]).unwrap();drop(c);
        let skipped=dispatch(&root,json!({"action":"query.run","args":{"project":project,"id":id,"onlyPending":true,"executionId":"skip"}})).unwrap();
        assert_eq!(skipped["queries"][0]["activeRun"],"old");assert!(!root.join("data/research/ncbi.lock").exists());
        dispatch(&root,json!({"action":"query.cancel","args":{"project":project,"id":id,"executionId":"stop"}})).unwrap();
        let stopped=dispatch(&root,json!({"action":"query.run","args":{"project":project,"id":id,"executionId":"stop"}})).unwrap();
        assert_eq!(stopped["queries"][0]["activeRun"],"old");assert_eq!(stopped["queries"][0]["error"],"");
        assert_eq!(fs::read_to_string(&old_xml).unwrap(),"<PubmedArticleSet/>");assert!(!root.join("data/research/ncbi.lock").exists());
        fs::remove_file(old_xml).unwrap();let current=dispatch(&root,json!({"action":"workspace","args":{"project":project}})).unwrap();assert_eq!(current["queries"][0]["xmlExists"],false);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn query_cancel_interrupts_rate_limit_lock_and_retry_wait() {
        let root=temp();let c=db(&root).unwrap();let cancel=root.join("cancel");
        let lock=OpenOptions::new().create(true).truncate(false).read(true).write(true).open(root.join("data/research/ncbi.lock")).unwrap();lock.lock_exclusive().unwrap();
        let marker=cancel.clone();let stop=std::thread::spawn(move||{std::thread::sleep(Duration::from_millis(150));fs::write(marker,b"stop").unwrap();});
        let start=std::time::Instant::now();assert_eq!(ncbi(&root,&c,"esearch",vec![],Some(&cancel)).unwrap_err(),QUERY_CANCELLED);assert!(start.elapsed()<Duration::from_secs(2));stop.join().unwrap();
        assert_eq!(query_wait(Duration::from_secs(8),Some(&cancel)).unwrap_err(),QUERY_CANCELLED);
        drop(lock);drop(c);fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn query_cancel_drops_pending_http_headers_and_body() {
        use std::net::TcpListener;
        for body_started in [false,true] {
            let root=temp();let marker=root.join("stop");let cancel=marker.clone();
            let listener=TcpListener::bind("127.0.0.1:0").unwrap();let address=listener.local_addr().unwrap();
            let server=std::thread::spawn(move||{
                let (mut socket,_)=listener.accept().unwrap();socket.set_read_timeout(Some(Duration::from_secs(3))).unwrap();
                let mut reader=BufReader::new(socket.try_clone().unwrap());let mut length=0;
                loop {let mut line=String::new();reader.read_line(&mut line).unwrap();if line=="\r\n"{break;}if let Some(v)=line.to_lowercase().strip_prefix("content-length:"){length=v.trim().parse::<usize>().unwrap();}}
                let mut body=vec![0;length];reader.read_exact(&mut body).unwrap();
                if body_started {socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 10000\r\n\r\npartial").unwrap();socket.flush().unwrap();}
                std::thread::sleep(Duration::from_millis(100));fs::write(marker,b"stop").unwrap();
                let mut byte=[0];assert_eq!(reader.read(&mut byte).unwrap(),0,"cancellation must close the HTTP connection");
            });
            let start=std::time::Instant::now();assert_eq!(ncbi_post(&format!("http://{address}"),&[("term".into(),"test".into())],Some(&cancel)).unwrap_err(),QUERY_CANCELLED);assert!(start.elapsed()<Duration::from_secs(2));server.join().unwrap();fs::remove_dir_all(root).unwrap();
        }
    }

    #[test]
    fn qualified_target_refills_in_rank_order_reuses_candidates_and_preserves_failed_run() {
        let root=temp();let p="test";
        let saved=dispatch(&root,json!({"action":"query.save","args":{"project":p,"name":"Query","text":"kidney"}})).unwrap();
        let id=s(&saved["queries"][0],"id").to_string();let mut c=db_project(&root,p).unwrap();
        write_file(&root.join("data/reference/jcr/fixture.json"),json!([{"journal":"A","quartile":"Q1"},{"journal":"B","quartile":"Q3"}]).to_string().as_bytes()).unwrap();
        put(&c,"jcr",&json!({"version":"fixture"})).unwrap();
        let mut f=defaults();f["limit"]=json!(3);f["jcr"]=json!(true);f["quartiles"]=json!(["Q1","Q2"]);put(&c,&format!("queryFilters:{id}"),&f).unwrap();
        let article=|n:usize|format!("<PubmedArticle><MedlineCitation><PMID>{n}</PMID><Article><ArticleTitle>Title {n}</ArticleTitle><Journal><Title>{}</Title></Journal><Abstract><AbstractText Label=\"RESULTS\">{}</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>",if n<=2 || n>100 {"A"} else {"B"},if n==2 {"   "} else {"Useful abstract"});
        let xml=|start,end|format!("<PubmedArticleSet>{}</PubmedArticleSet>",(start..=end).map(&article).collect::<String>());
        let search=json!({"esearchresult":{"count":"105","idlist":(1..=105).map(|n|n.to_string()).collect::<Vec<_>>()}}).to_string();
        let fixture=|responses:Value|write_file(&root.join("ncbi-fixture.json"),json!({"responses":responses}).to_string().as_bytes()).unwrap();
        fixture(json!([{"endpoint":"esearch","body":search},{"endpoint":"efetch","body":xml(1,100)},{"endpoint":"efetch","body":xml(101,105)}]));
        let result=run_query(&root,&mut c,p,&id,None,false).unwrap();
        assert_eq!(result["queries"][0]["run"]["qualified"],3);assert_eq!(result["corpus"]["included"],3);
        let ids=result["corpus"]["papers"].as_array().unwrap().iter().filter(|a|a["included"]==true).map(|a|s(a,"pmid")).collect::<Vec<_>>();assert_eq!(ids,vec!["1","101","102"]);
        assert!(result["corpus"]["papers"].as_array().unwrap().iter().any(|a|a["pmid"]=="2" && a["reason"]=="XML 无有效摘要"));
        f["limit"]=json!(4);put(&c,&format!("queryFilters:{id}"),&f).unwrap();
        let more=run_query(&root,&mut c,p,&id,None,false).unwrap();assert_eq!(more["corpus"]["included"],4);
        f["limit"]=json!(30);put(&c,&format!("queryFilters:{id}"),&f).unwrap();
        let exhausted=run_query(&root,&mut c,p,&id,None,false).unwrap();assert_eq!(exhausted["corpus"]["included"],6);assert_eq!(exhausted["queries"][0]["stale"],false);
        let old=exhausted["queries"][0]["activeRun"].clone();
        fixture(json!([{"endpoint":"esearch","body":search},{"endpoint":"efetch","body":xml(1,99)}]));
        assert!(run_query(&root,&mut c,p,&id,None,true).is_err());assert_eq!(workspace(&root,&c,p).unwrap()["queries"][0]["activeRun"],old);
        fs::remove_dir_all(root).unwrap();
    }

}
