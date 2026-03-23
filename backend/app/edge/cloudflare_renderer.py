from __future__ import annotations

from .models import CloudflareSettings, CorePublicIdentity, EdgePublication


class CloudflareConfigRenderer:
    def render(
        self,
        *,
        identity: CorePublicIdentity,
        settings: CloudflareSettings,
        publications: list[EdgePublication],
    ) -> dict[str, object]:
        ingress: list[dict[str, object]] = [
            {"hostname": identity.public_hostname, "path": "/api/*", "service": "http://127.0.0.1:9001"},
            {"hostname": identity.public_hostname, "path": "/nodes/proxy/*", "service": "http://127.0.0.1:9001"},
            {"hostname": identity.public_hostname, "path": "/addons/proxy/*", "service": "http://127.0.0.1:9001"},
        ]
        for publication in sorted(publications, key=lambda item: (item.hostname, item.path_prefix, item.publication_id)):
            if not publication.enabled:
                continue
            ingress.append(
                {
                    "hostname": publication.hostname,
                    "path": publication.path_prefix,
                    "service": publication.target.upstream_base_url,
                }
            )
        ingress.append({"hostname": identity.public_hostname, "service": "http://127.0.0.1:80"})
        ingress.append({"service": "http_status:404"})
        return {
            "tunnel": settings.tunnel_id,
            "credentials-file": settings.credentials_reference,
            "tunnel-token-ref": settings.tunnel_token_ref,
            "managed-domain-base": settings.managed_domain_base,
            "ingress": ingress,
        }
