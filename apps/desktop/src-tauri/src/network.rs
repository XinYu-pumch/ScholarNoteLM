//! System proxy discovery is performed when each HTTP client is created.
//! Never retain a client across independent requests: proxy changes must apply
//! without restarting the desktop process. Active responses keep their route.
use reqwest::Url;
use std::net::IpAddr;

pub fn bypass(url: &str) -> bool {
    let Ok(url) = Url::parse(url) else { return false; };
    let host = url.host_str().unwrap_or("").trim_matches(['[', ']']).trim_end_matches('.');
    if host == "localhost" || host.ends_with(".localhost") || host.parse::<IpAddr>().is_ok_and(|ip| {
        ip.is_loopback() || matches!(ip, IpAddr::V6(v) if v.to_ipv4_mapped().is_some_and(|v|v.is_loopback()))
    }) { return true; }
    system_bypass(host)
}

#[cfg(target_os = "macos")]
fn system_bypass(host: &str) -> bool {
    use system_configuration::core_foundation::{array::CFArray, base::{CFType, TCFType}, number::CFNumber, string::CFString};
    use system_configuration::dynamic_store::SCDynamicStoreBuilder;
    // Environment overrides and NO_PROXY are handled by reqwest itself.
    if ["HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"]
        .iter().any(|name| std::env::var(name).is_ok_and(|value| !value.is_empty())) { return false; }
    let Some(store) = SCDynamicStoreBuilder::new("ScholarNoteLM").build() else { return false; };
    let Some(settings) = store.get_proxies() else { return false; };
    if !host.contains('.') && settings.find(CFString::new("ExcludeSimpleHostnames"))
        .and_then(|v| v.downcast::<CFNumber>()).and_then(|v|v.to_i32()) == Some(1) { return true; }
    settings.find(CFString::new("ExceptionsList"))
        .and_then(|v| v.downcast::<CFArray>())
        .is_some_and(|values| values.iter().any(|v| unsafe { CFType::wrap_under_get_rule(*v) }
            .downcast::<CFString>().is_some_and(|v| exception_matches(host, &v.to_string()))))
}

#[cfg(not(target_os = "macos"))]
fn system_bypass(_host: &str) -> bool { false } // Windows bypass is read by reqwest.

#[cfg(any(target_os = "macos", test))]
fn exception_matches(host: &str, rule: &str) -> bool {
    let rule = rule.trim().to_ascii_lowercase();
    if let Some((network, bits)) = rule.split_once('/') {
        if let (Ok(host), Ok(network), Ok(bits)) = (host.parse::<std::net::Ipv4Addr>(), network.parse::<std::net::Ipv4Addr>(), bits.parse::<u32>()) {
            if bits <= 32 { let mask = u32::MAX.checked_shl(32 - bits).unwrap_or(0); return u32::from(host) & mask == u32::from(network) & mask; }
        }
        return false;
    }
    let pattern = format!("^{}$", regex::escape(&rule).replace(r"\*", ".*").replace(r"\?", "."));
    regex::Regex::new(&pattern).is_ok_and(|r|r.is_match(&host.to_ascii_lowercase()))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn loopback_never_uses_proxy() {
        for host in ["localhost", "localhost.", "test.localhost", "127.0.0.1", "127.12.3.4", "[::1]", "[::ffff:127.0.0.1]"] {
            assert!(bypass(&format!("http://{host}:1234/v1")), "{host}");
        }
    }
    #[test]
    fn mac_exceptions_match_wildcards_and_subnets() {
        assert!(exception_matches("printer.local", "*.local"));
        assert!(exception_matches("192.168.2.3", "192.168.0.0/16"));
        assert!(exception_matches("anything.example", "*"));
        assert!(!exception_matches("192.169.2.3", "192.168.0.0/16"));
        assert!(!exception_matches("example.com.evil", "example.com"));
    }
}
