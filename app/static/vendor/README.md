# Gevendorde front-end-bestanden

Deze bestanden staan bewust in de repo in plaats van via een CDN: de app
haalt niets van andere servers en de Content-Security-Policy blijft op
`'self'`. Werk ze alleen bij met een nieuwe, vastgepinde versie en
controleer de checksum van het npm-pakket (`dist.integrity`).

| Bestand | Bron (npm) | Licentie | SHA-256 |
|---|---|---|---|
| `htmx/htmx.min.js` | `htmx.org@2.0.11` (`dist/htmx.min.js`) | 0BSD (`htmx/LICENSE`) | `d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717` |
| `figtree/figtree-latin-wght-normal.woff2` | `@fontsource-variable/figtree@5.3.0` (`files/`) | OFL 1.1 (`figtree/OFL.txt`) | `4ba7d3d096695818fe0686be4f1e82c6b05134e18a22260336130335027462dd` |
| `figtree/figtree-latin-ext-wght-normal.woff2` | `@fontsource-variable/figtree@5.3.0` (`files/`) | OFL 1.1 (`figtree/OFL.txt`) | `bf7828e2c258cffcfa50a048ee388a36b95bc16b452e8d36fa797635dbe15965` |

npm-integriteit van de pakketten (gecontroleerd bij het ophalen):

- `htmx.org-2.0.11.tgz`: `sha512-Thx/WtpeOQqSrqBCw/A1cwGJGg4UrVa3+sW0GmrM3p4gJgO89ecH4qtbnyzDDWFvBTqjnIMCgELTNt636dtamA==`
- `figtree-5.3.0.tgz`: `sha512-VRVodD7OiG7apQwE8/2fMjaqpY/a0qRJqL5HtYj8CKIVps+9amaFcdfKmDIf7iqYQx6iPLlArVXAfKeIZmVcNQ==`

Controleren: `sha256sum app/static/vendor/*/*.js app/static/vendor/*/*.woff2`
