#coding:utf8
#title_en: MissAV Downloader
#comment: For missav.ws, missav.ai, missav.com, njavtv.com - Explicit domains
from utils import Downloader, try_n, LazyUrl, get_print, Soup, clean_title, Session
from error_printer import print_error
from m3u8_tools import M3u8_stream
# from downloader import download # Using session.get for thumbnail
from io import BytesIO
import urllib.parse
import re
import json
import requests # For requests.exceptions.HTTPError

# Define a common User-Agent
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'

class Video:
    def __init__(self, url, cwz):
        self.cw = cwz
        self.print_ = get_print(self.cw)
        
        self.session = Session()
        self.session.headers.update({'User-Agent': USER_AGENT})

        extraction_result = self.getx(url)
        if extraction_result is None:
            self.print_("Failed to extract video data from getx.")
            raise ValueError("getx did not return video data.")

        deobfuscated_base_url, page_origin_for_referer, self.uth, self.filename = extraction_result

        self.print_(f"Base M3U8 URL from getx/deobfuscate: {deobfuscated_base_url}")
        if page_origin_for_referer:
            self.print_(f"Determined Referer Origin for subsequent requests: {page_origin_for_referer}")
        self.print_(f"Thumbnail URL: {self.uth}")
        self.print_(f"Selected Filename: {self.filename}")

        if not deobfuscated_base_url:
            self.print_("No base M3U8 URL candidate found.")
            raise ValueError("Base M3U8 URL could not be obtained.")

        actual_media_playlist_url_to_use = None
        m3u8_content = None
        
        base_url_path = ""
        if deobfuscated_base_url.count('/') > 2: 
            base_url_path = deobfuscated_base_url.rsplit('/', 1)[0] 
        else: 
            self.print_(f"Warning: deobfuscated_base_url '{deobfuscated_base_url}' does not have a typical path for M3U8.")
            base_url_path = deobfuscated_base_url 

        original_filename_from_getx = deobfuscated_base_url.rsplit('/', 1)[-1] if deobfuscated_base_url.count('/') > 2 else "default.m3u8"

        m3u8_filename_candidates = [
            original_filename_from_getx,
            'playlist.m3u8',
            'video.m3u8',
            'list.m3u8',
            'source.m3u8', 
            '720p/video.m3u8' 
        ]
        unique_candidates = list(dict.fromkeys(m3u8_filename_candidates))

        m3u8_fetch_headers = {
            'User-Agent': USER_AGENT,
            'Referer': page_origin_for_referer,
            'Origin': page_origin_for_referer.rstrip('/'),
        }

        for filename_candidate in unique_candidates:
            if base_url_path.endswith('/'):
                 current_m3u8_url_to_try = f"{base_url_path}{filename_candidate}"
            else:
                 current_m3u8_url_to_try = f"{base_url_path}/{filename_candidate}"

            try:
                self.print_(f"Attempting to fetch M3U8 content from: {current_m3u8_url_to_try}")
                response = self.session.get(current_m3u8_url_to_try, headers=m3u8_fetch_headers)
                response.raise_for_status()
                m3u8_content = response.text
                actual_media_playlist_url_to_use = current_m3u8_url_to_try
                self.print_(f"Successfully fetched M3U8 content from: {current_m3u8_url_to_try}")
                break 
            except requests.exceptions.HTTPError as e_fetch:
                if e_fetch.response.status_code == 404:
                    self.print_(f"Got 404 for {current_m3u8_url_to_try}. Trying next candidate...")
                else:
                    self.print_(f"HTTP error {e_fetch.response.status_code} for {current_m3u8_url_to_try}: {print_error(e_fetch)}")
            except Exception as e_fetch:
                self.print_(f"Failed to fetch M3U8 {current_m3u8_url_to_try}: {print_error(e_fetch)}")
        
        if not m3u8_content:
            self.print_("Failed to fetch M3U8 content from all candidates.")
            actual_media_playlist_url_to_use = deobfuscated_base_url 

        if m3u8_content and "#EXT-X-STREAM-INF:" in m3u8_content:
            self.print_("Master playlist detected. Parsing for variant streams...")
            lines = m3u8_content.strip().split('\n')
            variant_urls_info = []
            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF:"):
                    try:
                        current_bandwidth = 0
                        if "BANDWIDTH=" in line:
                            bandwidth_str = line.split("BANDWIDTH=")[1].split(",")[0]
                            if bandwidth_str.isdigit():
                                current_bandwidth = int(bandwidth_str)
                        if i + 1 < len(lines) and not lines[i+1].startswith("#"):
                            relative_url = lines[i+1].strip()
                            absolute_variant_url = urllib.parse.urljoin(actual_media_playlist_url_to_use, relative_url)
                            variant_urls_info.append({'url': absolute_variant_url, 'bandwidth': current_bandwidth, 'relative': relative_url})
                    except Exception as e_parse_inf:
                        self.print_(f"Error parsing #EXT-X-STREAM-INF line: {line} - {e_parse_inf}")
            
            if variant_urls_info:
                variant_urls_info.sort(key=lambda x: x.get('bandwidth', 0), reverse=True)
                actual_media_playlist_url_to_use = variant_urls_info[0]['url']
                self.print_(f"Selected variant (highest bandwidth): {actual_media_playlist_url_to_use} (from relative: {variant_urls_info[0]['relative']})")
            else:
                self.print_("No variant streams found in master playlist. Using fetched master/media URL directly.")
        
        elif m3u8_content: 
             self.print_("Media playlist detected or Master playlist parsing failed. Using fetched URL directly.")
        
        if not actual_media_playlist_url_to_use and deobfuscated_base_url:
            self.print_("M3U8 content fetching failed. Using the base URL from deobfuscation as a last resort for M3u8_stream.")
            actual_media_playlist_url_to_use = deobfuscated_base_url
        elif not actual_media_playlist_url_to_use:
             self.print_("CRITICAL: No valid M3U8 URL could be determined after all attempts.")
             raise ValueError("No M3U8 URL could be set for M3u8_stream.")

        stream_obj = None
        last_exception = None
        if actual_media_playlist_url_to_use:
            self.print_(f"Attempting M3u8_stream with final URL: {actual_media_playlist_url_to_use}")
            m3u8_referer_to_use = page_origin_for_referer 
            try:
                self.print_(f"Using Referer for M3u8_stream: {m3u8_referer_to_use}")
                stream_obj = M3u8_stream(
                    actual_media_playlist_url_to_use,
                    referer=m3u8_referer_to_use,
                    deco=self.cbyte,
                    n_thread=4,
                    session=self.session 
                )
                self.print_(f"Successfully initialized M3u8_stream with: {actual_media_playlist_url_to_use}")
            except TypeError as te: 
                self.print_(f"TypeError during M3u8_stream init (session arg might not be supported): {print_error(te)}")
                self.print_("Retrying M3u8_stream without session argument.")
                try:
                    stream_obj = M3u8_stream(
                        actual_media_playlist_url_to_use,
                        referer=m3u8_referer_to_use,
                        deco=self.cbyte,
                        n_thread=4
                    )
                    self.print_(f"Successfully initialized M3u8_stream (no session arg) with: {actual_media_playlist_url_to_use}")
                except Exception as e_minimal:
                    last_exception = e_minimal
                    self.print_(f"M3u8_stream initialization failed (no session arg): {print_error(e_minimal)}")
            except Exception as e: 
                last_exception = e
                self.print_(f"M3u8_stream initialization failed: {print_error(e)}")
                if m3u8_content:
                    self.print_("M3u8_stream failed. Content of the fetched M3U8 was:")
                    self.print_(m3u8_content[:1000])
        else:
            self.print_("No valid M3U8 URL to process for M3u8_stream.")
            if not last_exception: 
                 last_exception = ValueError("No M3U8 URL available to initialize M3u8_stream.")

        if stream_obj is None:
            self.print_("M3u8_stream could not be initialized.")
            if last_exception:
                raise last_exception 
            else: 
                raise ValueError("M3u8_stream could not be initialized (unknown reason).")

        if hasattr(stream_obj, 'live') and stream_obj.live is not None:
             self.print_("Stream has 'live' attribute. (Handling may be needed)")

        self.th = BytesIO()
        if self.uth:
            try:
                self.print_(f"Downloading thumbnail: {self.uth}")
                thumb_headers = {
                    'User-Agent': USER_AGENT,
                    'Referer': page_origin_for_referer if page_origin_for_referer else url 
                }
                thumb_response = self.session.get(self.uth, headers=thumb_headers)
                thumb_response.raise_for_status()
                self.th.write(thumb_response.content) 
                self.th.seek(0) 
            except Exception as e:
                self.print_(f"Thumbnail download error: {print_error(e)}")
        else:
            self.print_("No thumbnail URL (self.uth) to download.")

        self.url = LazyUrl(url, lambda _: stream_obj, self)

    def cbyte(self, dato):
        return dato[8:]

    def deobfuscate_missav_source(self, packed_code_params, keywords_str):
        direct_m3u8_regex = r"""(?:file|source|src|f)\s*[:=]\s*(["'])(https?://(?:[a-zA-Z0-9.\-_]+|\[[a-fA-F0-9:]+\])(?:[:\d]+)?(?:/(?:[\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])?)?\.m3u8(?:[\?&][\w.,@?^=%&:/~+#-=]*)?)\1"""
        match_direct = re.search(direct_m3u8_regex, packed_code_params, re.VERBOSE | re.IGNORECASE)
        if match_direct:
            extracted_url = match_direct.group(2)
            self.print_(f"Deobfuscate (Direct M3U8v2 from packed_code): {extracted_url}")
            return extracted_url
        
        simple_url_match = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", packed_code_params)
        if simple_url_match:
            extracted_url = simple_url_match.group(1)
            self.print_(f"Deobfuscate (Simple M3U8 from packed_code): {extracted_url}")
            return extracted_url
        
        self.print_("Direct M3U8 URL not found in packed_code. Attempting keyword-based reconstruction.")
        if not keywords_str:
            self.print_("Keywords string is empty, cannot perform keyword-based reconstruction.")
            return None

        keywords = keywords_str.split('|')
        idx_map_p1 = {'name':"DefaultPattern(reconstruct)", 'protocol_idx':8, 'domain1_idx':7, 'domain2_idx':6, 'path_indices':[5,4,3,2,1], 'path_separator':'-', 'filename_idx':14, 'extension_idx':0}
        patterns = [idx_map_p1] 

        for num, patt in enumerate(patterns): 
            p_name = patt.get('name', f"Pattern{num+1}")
            try:
                req_idx_values = {'protocol': patt['protocol_idx'], 'domain1': patt['domain1_idx'], 
                                  'domain2': patt['domain2_idx'], 'filename': patt['filename_idx'], 
                                  'extension': patt['extension_idx']}
                req_idx_check = list(req_idx_values.values()) + patt['path_indices']
                                
                if any(idx >= len(keywords) for idx in req_idx_check): 
                    missing_indices_detail = {k:v for k,v in req_idx_values.items() if v >= len(keywords)}
                    missing_path_indices = [pi for pi in patt['path_indices'] if pi >=len(keywords)]
                    self.print_(f"KeywordReconstruct {p_name}: Index out of bounds. Keywords len: {len(keywords)}. Missing primary: {missing_indices_detail}, Missing path idx: {missing_path_indices}")
                    continue

                proto = keywords[patt['protocol_idx']] 
                domain_part1 = keywords[patt['domain1_idx']] 
                domain_part2 = keywords[patt['domain2_idx']] 
                domain = f"{domain_part1}.{domain_part2}"

                path_segments_keywords = [keywords[i] for i in patt['path_indices']] 
                path_base = patt['path_separator'].join(path_segments_keywords) 

                filename_keyword = keywords[patt['filename_idx']] 
                extension_keyword = keywords[patt['extension_idx']] 
                
                reconstructed_url = f"{proto}://{domain}/{path_base}/{filename_keyword}.{extension_keyword}"
                
                if reconstructed_url.endswith(f".{extension_keyword}"): 
                    self.print_(f"Deobfuscate ({p_name}) generated base URL: {reconstructed_url}")
                    return reconstructed_url 
                else: 
                    self.print_(f"KeywordReconstruct {p_name}: Generated URL is not .{extension_keyword} - {reconstructed_url}")
            except IndexError:
                self.print_(f"KeywordReconstruct {p_name} Index Error.")
            except Exception as e:
                self.print_(f"KeywordReconstruct {p_name} Exception: {print_error(e)}")
        
        self.print_(f"M3U8 URL keyword reconstruction failed. Packed (first 150): {packed_code_params[:150]}, Keywords (first 100): {keywords_str[:100] if keywords_str else 'N/A'}")
        return None

    @try_n(2)
    def getx(self, url): 
        self.print_ = get_print(self.cw) 
        self.print_(f"Fetching main page for MissAV: {url}")

        parsed_url = urllib.parse.urlparse(url)
        page_get_headers = {
            'User-Agent': USER_AGENT, 
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': f'{parsed_url.scheme}://{parsed_url.netloc}/',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Ch-Ua': '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
        }

        self.print_(f"Attempting to fetch main page with session and enhanced headers.")

        try:
            response = self.session.get(url, headers=page_get_headers)
            response.raise_for_status() 
            page_source = response.text
        except Exception as e_main_fetch:
            self.print_(f"CRITICAL: Failed to fetch main page {url} using session: {print_error(e_main_fetch)}")
            raise

        soup = Soup(page_source)
        video_title = "missav_video" 
        try:
            title_h1 = soup.find('h1') 
            if title_h1 and title_h1.text:
                title_text = title_h1.text.strip()
                if '/video/' not in url:
                    og_url_tag = soup.find('meta', {'property': 'og:url'})
                    if og_url_tag and og_url_tag.get('content'):
                        content_url = og_url_tag['content']
                        code_part = content_url[content_url.rfind('/')+1:].upper()
                        space_index = title_text.find(' ')
                        if space_index == -1: 
                            title_text = code_part + title_text
                        else:
                            title_text = code_part + title_text[space_index:] 
                video_title = clean_title(title_text)
            else: 
                self.print_("H1 title not found or empty, trying og:title...")
                og_title_tag = soup.find('meta', property='og:title')
                if og_title_tag and og_title_tag.get('content'):
                    video_title = clean_title(og_title_tag['content'].strip())
                else:
                    self.print_("og:title not found, trying <title> tag...")
                    page_title_tag = soup.find('title')
                    if page_title_tag and page_title_tag.string:
                        video_title = clean_title(page_title_tag.string.strip())
        except Exception as e_title: 
            self.print_(f"Error extracting title: {print_error(e_title)}")
        
        if len(video_title) > 60: 
            video_title = video_title[:60]
        
        filename_final = video_title + '.mp4'

        thumb_url = None
        try:
            og_image_tag = soup.find('meta', {'property':'og:image'}) 
            if og_image_tag and og_image_tag.get('content'):
                thumb_url = og_image_tag['content']
            
            if not thumb_url: 
                self.print_("Thumbnail from og:image not found. Trying JSON-LD...")
                script_tag_json_ld_list = soup.find_all('script', type='application/ld+json')
                for script_tag_json_ld in script_tag_json_ld_list:
                    if script_tag_json_ld.string:
                        try:
                            json_ld_data = json.loads(script_tag_json_ld.string)
                            items_to_check = [json_ld_data] if not isinstance(json_ld_data, list) else json_ld_data
                            for item in items_to_check:
                                if isinstance(item, dict) and item.get('@type') == 'VideoObject' and item.get('thumbnailUrl'):
                                    thumb_url_candidate = item['thumbnailUrl']
                                    thumb_url = thumb_url_candidate[0] if isinstance(thumb_url_candidate, list) and thumb_url_candidate else (thumb_url_candidate if isinstance(thumb_url_candidate, str) else None)
                                    if thumb_url: break
                            if thumb_url: break
                        except json.JSONDecodeError: 
                            self.print_(f"JSON-LD decode error in script tag (first 100): {script_tag_json_ld.string[:100]}")
                    if thumb_url: break 
        except Exception as e_thumb: 
            self.print_(f"Error extracting thumbnail: {print_error(e_thumb)}")
        self.print_(f"Found thumbnail URL (uth): {thumb_url}")

        m3u8_found_links = []
        deobfuscated_m3u8_url_from_packer = None 

        for eval_script_tag in soup.find_all('script'):
            if eval_script_tag.string:
                script_content = eval_script_tag.string
                packer_eval_match = re.search(r"eval\s*\(\s*function\s*\(p,\s*a,\s*c,\s*k,\s*e,\s*d\s*\)\s*\{.*return\s+p}\s*\((.*)\)\)", script_content, re.DOTALL | re.IGNORECASE)
                if packer_eval_match:
                    self.print_(f"Found P.A.C.K.E.R. script block...")
                    eval_args_str = packer_eval_match.group(1).strip()
                    
                    pcode, kstr = "", ""
                    pcode_match = re.match(r"(['\"])(.*?)\1\s*,", eval_args_str)
                    if pcode_match:
                        pcode_raw = pcode_match.group(2)
                        pcode = pcode_raw.replace(r"\\'", "'") if pcode_match.group(1) == "'" else pcode_raw.replace(r'\\"', '"')
                    else:
                        self.print_("  Failed to extract pcode from P.A.C.K.E.R. arguments.")
                        continue
                    
                    kstr_match = re.search(r""" ,\s* (['"]) ((?:\\.|(?!\1)[^\\\r\n])*) \1 \.split\(\s*['"]\|['"]\s*\) """, eval_args_str, re.VERBOSE)
                    if kstr_match:
                        kstr_raw = kstr_match.group(2)
                        kstr = kstr_raw.replace(r"\\'", "'") if kstr_match.group(1) == "'" else kstr_raw.replace(r'\\"', '"')
                    else:
                        self.print_("  kstr (keyword string before .split('|')) not found or pattern mismatch.")
                    
                    if pcode:
                        self.print_(f"Attempting deobfuscation with pcode (kstr presence: {'Yes' if kstr else 'No'})")
                        deob_url_candidate = self.deobfuscate_missav_source(pcode, kstr if kstr else "")
                        if deob_url_candidate:
                            self.print_(f"Deobfuscated URL from P.A.C.K.E.R.: {deob_url_candidate}")
                            if deob_url_candidate.startswith("http") and ".m3u8" in deob_url_candidate: 
                                deobfuscated_m3u8_url_from_packer = deob_url_candidate 
                                break 
                            else: 
                                self.print_(f"Deobfuscated content is not a valid M3U8 URL: {deob_url_candidate}")
                        else: 
                            self.print_("Deobfuscation returned None for this P.A.C.K.E.R. block.")
            if deobfuscated_m3u8_url_from_packer: break 
        
        if not deobfuscated_m3u8_url_from_packer:
            self.print_("P.A.C.K.E.R. deobfuscation did not yield M3U8. Searching for direct M3U8 links (fallback).")
            direct_m3u8_pattern = r"""(?:file|source|src|f)\s*[:=]\s*(["'])(https?://(?:[a-zA-Z0-9.\-_]+|\[[a-fA-F0-9:]+\])(?:[:\d]+)?(?:/(?:[\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])?)?\.m3u8(?:[\?&][\w.,@?^=%&:/~+#-=]*)?)\1"""
            match_direct = re.search(direct_m3u8_pattern, page_source, re.VERBOSE | re.IGNORECASE)
            if match_direct: 
                deobfuscated_m3u8_url_from_packer = match_direct.group(2)
            if deobfuscated_m3u8_url_from_packer: 
                self.print_(f"Found direct M3U8 link (fallback): {deobfuscated_m3u8_url_from_packer}")
            else:
                simple_m3u8_match = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", page_source)
                if simple_m3u8_match: 
                    deobfuscated_m3u8_url_from_packer = simple_m3u8_match.group(1)
                if deobfuscated_m3u8_url_from_packer: 
                    self.print_(f"Found simple M3U8 link (fallback): {deobfuscated_m3u8_url_from_packer}")

        if not deobfuscated_m3u8_url_from_packer:
            self.print_("CRITICAL: Failed to find any M3U8 URL from P.A.C.K.E.R or fallbacks.")
            raise ValueError("M3U8 URL could not be extracted.")

        parsed_page_url_obj = urllib.parse.urlparse(url)
        page_origin_for_referer_val = f"{parsed_page_url_obj.scheme}://{parsed_page_url_obj.netloc}/"

        return deobfuscated_m3u8_url_from_packer, page_origin_for_referer_val, thumb_url, filename_final


class Downloader_missav(Downloader):
    type = 'missav'
    single=True
    strip_header=False
    # **** URLS 및 ACCEPT_COOKIES: 명시적 도메인 나열 버전 ****
    URLS=['missav.ws', 'missav.ai', 'missav.com', 'njavtv.com'] 
    display_name='MissAV'
    MAX_PARALLEL=2
    icon='base64:iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAMAAABEpIrGAAAAaVBMVEX+Yo4AAAD/Yo7+Y47////+Yo//Yo////7+Y4/mvcbvYof/AADQWXHnYoD7YYyqVVX2YYn+Yo3+/////v//Y46ZMzP//f7mu8X9aZL//Pz9Z5H5ep31xdH52uLziqX9h6jxl6/2ztj73uab0JJXAAAAI3RSTlP/AP//////////zgErp/wD3/3///8F/////////////////8G0tiwAAAGzSURBVHicZVOLcoMwDDNxAi1QCpSytnvv/z9ykp3Qdssd4S6WZUV2pLqvfhw0qAxj/3C4Abq2lqQhiEgt0nZ/AQcEhNGUBCxJDk+A46QM4mMwIa4yHe+As5KWEEGENIY+F8CRZ/XO4k4TsANEDgIm5i4WpABwkAbf5ADoo6pcArvKzilqKJWq80iAisX2rAN7CB0AbUkTXd8sYGZ4lRYA2GOqRV7iHF910Z2og3BcSe/BANg+xni6+m38VEIvY740FgGxie/FVMJGGTRrEgWgAUeMH9kSrMF/yVTuG0ZjnJv1JlbJU1ki4XoKgMXJc3GRLijUC+4GDU0uEZvGAOZvMQX/PePGsV6srt1/kFTatLfk+RS/TFLNqwwyOpeJnC39B41gS1lcRxoFdiPBNed4veUEzA1WL1Wo2WM0GlY3p8/NAc4Vra5aaHHjdP2+O+SLzeowTRTFD03K9hj/ztrNgUloFYPBg9l74WjbyCHgQ4s8uO6dXOoyctWRKsrCHJHGQGVoq3Pufja3SNjGng/HszeJqPP4cPj0qJN5GGijeH569nhtKlCBGv4/3vz84bs+P/9fOZAMztosBq4AAAAASUVORK5CYII='
    ACCEPT_COOKIES=[r'(.*\.)?missav\.ws', r'(.*\.)?missav\.ai', r'(.*\.)?missav\.com', r'(.*\.)?njavtv\.com']
    # **** (URLS, ACCEPT_COOKIES 수정 끝) ****

    @try_n(2)
    def read(self):
        video = Video(self.url, self.cw) 
        self.urls.append(video.url)
        self.title = video.filename 
        if hasattr(video, 'th') and video.th and video.th.getbuffer().nbytes > 0:
             self.setIcon(video.th)
        else:
             get_print(self.cw)("No thumbnail data to set icon in Downloader_missav.read")
