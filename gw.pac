function FindProxyForURL(url, host) {
  if (dnsDomainIs(host, "challenges.cloudflare.com")) return "DIRECT";
  if (dnsDomainIs(host, "satoshifaucet.io") && shExpMatch(url, "*cdn-cgi/*")) return "DIRECT";
  return "PROXY gate-as.vaultproxies.com:80";
}
