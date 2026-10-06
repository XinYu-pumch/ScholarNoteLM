//! Content-addressed, losslessly compressed XML. History keeps separate manifests.
use super::*;

pub(super) fn save(root: &Path, project: &str, bytes: &[u8]) -> R<String> {
    let relative = format!("pubmed/objects/{}.xml.gz", hash(bytes));
    let path = project_file(root, project, &relative)?;
    if path.is_file() {
        if read(&path)? != bytes { return Err("XML 快照内容校验失败".into()); }
    } else {
        let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        encoder.write_all(bytes).map_err(err)?;
        write_file(&path, &encoder.finish().map_err(err)?)?;
    }
    Ok(relative)
}

pub(super) fn read(path: &Path) -> R<Vec<u8>> {
    if path.extension().is_none_or(|v| v != "gz") { return fs::read(path).map_err(err); }
    let mut bytes = Vec::new();
    flate2::read::GzDecoder::new(File::open(path).map_err(err)?).read_to_end(&mut bytes).map_err(err)?;
    let name = path.file_name().and_then(|v| v.to_str()).ok_or("无效 XML 路径")?;
    let expected = name.strip_suffix(".xml.gz").ok_or("无效 XML 快照扩展名")?;
    if hash(&bytes) != expected { return Err("XML 快照内容校验失败".into()); }
    Ok(bytes)
}

pub(super) fn snapshot(root: &Path, project: &str, id: &str) -> R<Vec<u8>> {
    valid_id(id)?;
    let folder = project_file(root, project, &format!("pubmed/snapshots/{id}"))?;
    let manifest: Value = serde_json::from_slice(&fs::read(folder.join("manifest.json")).map_err(err)?).map_err(err)?;
    if let Some(relative) = manifest["xmlPath"].as_str() {
        read(&project_file(root, project, relative)?)
    } else {
        read(&folder.join("pubmed.xml"))
    }
}
