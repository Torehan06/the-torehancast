# House geography sources

Sources for `web/src/geo/cd2026.topo.json` (district map) and the centroids that order
`web/src/data/houseTiles.json` (tile cartogram). Raw downloads are kept, unmodified, in the
gitignored `data/archives/geo/<dir>/`. `web/scripts/geo/sources.mjs` checks each file's
sha256 before using it.

Rebuild: `cd web && npm run build:tiles && npm run build:districts`.

## Which lines are used on Nov 3, 2026

Seat counts follow the 2020-census apportionment (`src/torehancast/districts.py`). Lines
differ from the 119th Congress (2024) in nine states:

| State | Plan | Status (checked Oct 29, 2026) |
|---|---|---|
| TX | PLANC2333 (HB 4, 2nd called session 2025), signed Aug 29, 2025 | In use: the Supreme Court stayed the district-court injunction (Dec 4, 2025) |
| CA | AB 604 (ch. 96, Stats. 2025), adopted by Prop 50 on Nov 4, 2025 | In use: the Supreme Court denied relief Feb 4, 2026 |
| NC | SL 2025-95 (SB 249), Oct 22, 2025 | In use: a three-judge panel allowed it Nov 26, 2025 |
| OH | Ohio Redistricting Commission plan of Oct 31, 2025 | In use |
| UT | Court-ordered Map 1 (Third District Court, Nov 10, 2025) | In use: appeals and a repeal measure failed |
| FL | EOGPCRP2026 (HB 1-D, ch. 2026-229), signed May 4, 2026 | In use, under litigation |
| TN | 2026 extraordinary-session plan, signed May 7, 2026 | In use: a federal judge declined to block it (May 26, 2026) |
| AL | Livingston Congressional Plan 3-2023 | In use: the Supreme Court allowed it June 2, 2026 |
| LA | Act 2 of 2026 (SB 121), May 29, 2026 | In use; the House primary moved to Nov 3 (general Dec 12) |

Not redrawn for 2026, so they come from CD119:
- **Missouri:** the Supreme Court ordered the 2022 map for 2026 (Sept 25, 2026). The 2025 map is on the November ballot as a referendum.
- **Virginia:** the April 21, 2026 referendum map was voided by the Virginia Supreme Court (May 8). The U.S. Supreme Court denied a stay May 15.
- **Maryland:** the Aug 3–5, 2026 special session passed a constitutional amendment, not a map.
- **New York:** the Supreme Court restored NY-11's lines (Mar 2, 2026).

## Archived files

| Dir | File | Publisher and URL | Plan | Retrieved (UTC) | Bytes | sha256 |
|---|---|---|---|---|---|---|
| `us-cd119` | `cb_2025_us_cd119_500k.zip` | U.S. Census Bureau, 2025 cartographic boundary files (public domain): https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_cd119_500k.zip | 119th Congress districts, 1:500k; Last-Modified Apr 23, 2026 | 2026-10-29 19:20 | 7,067,743 | `8e804518d333d67e24e25c61767c6a7c78fd0a0852179e8cc19c36fd66011010` |
| `CA` | `ab604_districts_shapefile.zip` (served as `media/603`) | California Senate Elections and Constitutional Amendments Committee: https://selc.senate.ca.gov/media/603, listed on https://selc.senate.ca.gov/node/1171 | AB 604, chaptered Aug 21, 2025 (file dated Aug 18, 2025) | 2026-10-29 19:20 | 4,968,925 | `0adf00848210b81abb38b62f24f05a854dc1f8dcfec44c8af5a4eb847c481f74` |
| `FL` | `EOGPCRP2026.zip` | Florida Senate, "Shapefile with Population Data for GIS": https://www.flsenate.gov/PublishedContent/Session/Congressional/EOGPCRP2026.zip, listed on https://www.flsenate.gov/Session/Redistricting/Congressional | EOGPCRP2026, enacted by HB 1-D (ch. 2026-229); Last-Modified Apr 27, 2026 | 2026-10-29 19:20 | 1,293,119 | `253cfc70414929eeccd29f4c559746e480fb3d2b4e94c2fd02d3175a9923a789` |
| `UT` | `political_us_congress_districts_2026_to_2032.zip` | Utah Geospatial Resource Center (state GIS office), "Utah US Congress Districts 2026 to 2032", item `d3388c1f7d894ab789247f6442855d66`: https://opendata.gis.utah.gov/api/download/v1/items/d3388c1f7d894ab789247f6442855d66/shapefile?layers=0 | Court-ordered Map 1. The shapefile inside is dated Jun 25, 2026 | 2026-10-29 19:21 | 401,904 | `bc3bbe19da6c0b425e0dbd584ee6eb326d7cabe96dd50c1bd0b64b6f43f8e34b` |
| `AL` | `Livingston Congressional Plan 3-2023 Legal Description.pdf` | Alabama Secretary of State: https://www.sos.alabama.gov/sites/default/files/2026-5-14/Livingston%20Congressional%20Plan%203-2023%20Legal%20Description.pdf | Livingston Congressional Plan 3-2023 (legal description); Last-Modified May 14, 2026 | 2026-10-29 19:20 | 170,282 | `254eee5ec5c4fb48b81adb5c3cb7efd775544d6d36e892a38ea82e4cdb516ce7` |
| `AL-blocks` | `tl_2020_01_tabblock20.zip` | U.S. Census Bureau, TIGER/Line 2020 blocks for Alabama: https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_01_tabblock20.zip | 2020 tabulation blocks (to build AL from its legal description) | 2026-10-29 19:21 | 255,921,861 | `5d228872ccc680374631c1c71db6b7c362dc98e782ee3c4db111aa651df48468` |

Notes:
- **Utah:** the official source is UGRC, the state's GIS office, not the court (Törehan approved this Oct 29). On Oct 29 UGRC was regenerating its export ("Up to date download file is being generated"), so the file above is the cached export. Re-download once the new export is ready: if the sha256 changes, the court's later boundary adjustment may be in the new file.
- **Alabama:** the legal-description PDF can't be used as it stands. Its text is clipped in places: county names like "Russe County" and "Jeff County", and in District 6 a Jefferson County tract list that ends in "Tract 1140:", where no tract matches the blocks listed after it. A parser of the PDF got through the rest, but a plan can't be rebuilt from text with pieces missing. AL needs a shapefile or block assignment file for Livingston Plan 3-2023 from the Legislature's Reapportionment Office. The 2020 blocks above are kept only in case a block assignment file arrives without shapes.

## Still needed (blocked from this network)

`npm run build:districts` refuses to write `cd2026.topo.json` until these are archived. The
tiles ship regardless. Until then, they order these states' districts from CD119 shapes
(`houseTiles.json` lists them under `provisional`).

| State | What to get | Where | Why it isn't here |
|---|---|---|---|
| TX | PLANC2333 shapefile (`PLANC2333.zip`) | Texas Legislative Council Capitol Data Portal, https://data.capitol.texas.gov/dataset/planc2333 | 403 (Cloudflare) from this network |
| NC | Enacted 2025 congressional plan (SL 2025-95) shapefile | NC General Assembly, https://www.ncleg.gov/Redistricting/C2025E | 403 from this network |
| OH | Oct 31, 2025 congressional plan shapefile or block assignment file | Ohio Redistricting Commission, https://redistricting.ohio.gov/maps | connection times out |
| TN | 2026 congressional plan shapefile | TN General Assembly (capitol.tn.gov) or Secretary of State, https://sos.tn.gov/announcements/2026-congressional-redistricting | connection refused / 403 |
| AL | Livingston Congressional Plan 3-2023 shapefile or block assignment file | Alabama Legislature Reapportionment Office, https://alison.legislature.state.al.us/reapportionment | site pages time out; the SOS PDF is clipped (see above) |
| LA | Act 2 (SB 121) plan. It is defined on VTDs in "2026 Precinct Shapefiles (1-27-2026)" | Louisiana Legislature, https://legis.la.gov | DNS does not resolve |

To add one: save it under `data/archives/geo/<ST>/`, add `file`, `field` (district-number
attribute) and `sha256` to its `REDRAWN` entry in `web/scripts/geo/sources.mjs`, add a row
to the table above, then rerun both builds.

## How the build uses them

1. Each source is read with mapshaper, reprojected to WGS84 and dissolved by district number.
   CD119 supplies every state not in the redrawn list; at-large seats are `CD119FP = 00`.
2. Features are projected with d3 `geoAlbersUsa().scale(1300).translate([487.5, 305])`, the
   projection behind `us-atlas/states-albers-10m.json`.
3. Each state's districts are clipped to that state's us-atlas outline. Outline area that no
   district covers is mostly bays the 1:10m outline counts as land. Each such piece goes to the
   district it shares the most boundary with.
4. All districts are simplified together (Visvalingam, 0.35 px) and written as TopoJSON
   (quantization 50,000), keyed `NC-01` / `AK-AL`, with properties `{ state }`.
