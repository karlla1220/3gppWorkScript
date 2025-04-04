import ftplib
import os
import sys
import re
import zipfile
from datetime import datetime
from dataclasses import dataclass, field

# --- 설정 ---
FTP_HOST = "ftp.3gpp.org"
BASE_PATH = "/tsg_ran/WG1_RL1/"
AH_BASE_FOLDER = "TSGR1_AH" # 실제 Ad-Hoc 회의 상위 폴더 이름 (확인됨)
DOC_SUBDIR = "Docs"
DOWNLOAD_DIR = "3gpp_downloads" # 다운로드 받을 로컬 폴더 이름

# --- 사용자 입력 ---
# 1. 검색할 문서 번호 목록
target_doc_prefixes = [
    'R1-2204634', 'R1-2207032', 'R1-2209457', 'R1-2209802', 'R1-2212306',
    'R1-2211929', 'R1-2301111', 'R1-2301072', 'R1-2301113', 'R1-2303428',
    'R1-2303748', 'R1-2303430', 'R1-2305145', 'R1-2305390', 'R1-2305147',
    'R1-2306892', 'R1-2307794', 'R1-2307795',  'R1-2309304',
    'R1-2309309', 'R1-2309334', 'R1-2309335', 'R1-2311897', 'R1-2311902',
    'R1-2311919', 'R1-2401338', 'R1-2401336', 'R1-2403127', 'R1-2403129',
    'R1-2404898', 'R1-2404900', 'R1-2406612', 'R1-2406614', 'R1-2408680',
    'R1-2408682', 'R1-2410295', 'R1-2410297',
    'R1-2500957', 'R1-2500959', # 필요 시 주석 해제
]

#'R1-2308332'


# 2. 검색 시작/끝 회의 폴더 이름 (숫자가 포함된 정규 회의 폴더 이름)
#   예: "TSGR1_99" 부터 "TSGR1_118" 까지
#   이 범위에 해당하는 정규 회의들과 Ad-Hoc 회의 중 필터링 조건에 맞는 회의가 검색 대상이 됩니다.
start_meeting_range_folder = "TSGR1_107" # 예시: RAN1#109-e 회의부터
end_meeting_range_folder = "TSGR1_123"     # 예시: RAN1#118 회의까지
addAdhoc=True
adhocFilterText = "NR"

# --- 데이터 구조 정의 ---
@dataclass
class MeetingInfo:
    display_name: str   # 사용자에게 보여줄 이름 (e.g., "TSGR1_112", "TSGR1_AHs/2023_XYZ")
    ftp_path: str       # Docs 폴더의 부모 경로 (e.g., "/tsg_ran/WG1_RL1/TSGR1_112/")
    meeting_type: str   # 'Numbered', 'AH', 'Other'
    sort_key: tuple = field(default_factory=tuple) # 정렬을 위한 키 (main_num, sub_order)
    main_number: int = -1 # 정규 회의 번호 (AH는 -1 또는 다른 값)

# --- 함수 정의 ---

def parse_meeting_folder_name(folder_name):
    """
    폴더 이름을 분석하여 정규 회의 번호와 정렬 순서를 반환합니다.
    예: "TSGR1_100" -> (100, 0)
        "TSGR1_100b" -> (100, 1)
        "TSGR1_100bis" -> (100, 1)
        "TSGR1_100b-e" -> (100, 2)
        "TSGR1_100-e" -> (100, 3)
        그 외 -> (-1, 0)
    """
    match = re.match(r"TSGR1_(\d+)(.*)", folder_name)
    if match:
        main_num = int(match.group(1))
        suffix = match.group(2).lower()

        sub_order = 0
        if suffix in ['b', 'bis']:
            sub_order = 1
        elif suffix in ['b-e', 'bis-e', 'b_e']: # 다양한 형태 처리
            sub_order = 2
        elif suffix == '-e' or suffix == '_e':
            sub_order = 3
        # 필요 시 다른 suffix 규칙 추가

        return main_num, sub_order
    return -1, 0

def get_meeting_list(ftp):
    """FTP 서버에서 회의 목록을 가져와 MeetingInfo 객체 리스트로 반환합니다."""
    meetings = []
    try:
        ftp.cwd(BASE_PATH)
        print(f"기본 경로 진입: {BASE_PATH}")
        base_items = ftp.nlst()
        print(f"'{BASE_PATH}' 에서 {len(base_items)}개 항목 발견.")

        for item in base_items:
            item_path = f"{BASE_PATH}{item}/"

            # 1. 정규 회의 폴더 처리
            main_num, sub_order = parse_meeting_folder_name(item)
            if main_num != -1:
                meetings.append(MeetingInfo(
                    display_name=item,
                    ftp_path=item_path,
                    meeting_type='Numbered',
                    sort_key=(main_num, sub_order),
                    main_number=main_num
                ))
                continue # 다음 항목으로

            # 2. Ad-Hoc 회의 폴더 처리 (AH_BASE_FOLDER = "TSGR1_AH")
            if item == AH_BASE_FOLDER:
                ah_base_path = item_path
                try:
                    ftp.cwd(ah_base_path)
                    print(f"Ad-Hoc 기본 경로 진입: {ah_base_path}")
                    ah_sub_folders = ftp.nlst()
                    print(f"  -> {len(ah_sub_folders)}개의 Ad-Hoc 회의 후보 발견.")
                    for sub_ah_folder in ah_sub_folders:
                        # AH 하위 폴더 이름에 '.'이 없는 경우만 디렉토리로 간주 (간단한 필터링)
                        if '.' not in sub_ah_folder:
                            ah_meeting_path = f"{ah_base_path}{sub_ah_folder}/"
                            meetings.append(MeetingInfo(
                                display_name=f"{AH_BASE_FOLDER}/{sub_ah_folder}",
                                ftp_path=ah_meeting_path,
                                meeting_type='AH'
                                # AH 회의는 정렬 키나 번호가 중요하지 않으므로 기본값 사용
                            ))
                        else:
                            print(f"  -> '{sub_ah_folder}'는 Ad-Hoc 하위 폴더가 아닌 것으로 간주하여 건너뜁니다.")

                    ftp.cwd(BASE_PATH) # AH 탐색 후 기본 경로로 복귀
                except ftplib.error_perm as e:
                    print(f"오류: Ad-Hoc 경로 '{ah_base_path}' 접근 불가: {e}")
                    ftp.cwd(BASE_PATH) # 오류 발생 시에도 기본 경로 복귀 시도
                except Exception as e:
                    print(f"오류: Ad-Hoc 폴더 처리 중 오류 발생: {e}")
                    ftp.cwd(BASE_PATH) # 오류 발생 시에도 기본 경로 복귀 시도
                continue # 다음 항목으로

            # 3. 기타 항목 (로그 등) - 필요시 처리
            # print(f"기타 항목 '{item}' 건너뜁니다.")

        # 최종 회의 목록 정렬 (정규 회의 우선, 번호/순서 기준)
        meetings.sort(key=lambda m: m.sort_key if m.meeting_type == 'Numbered' else (float('inf'), 0)) # AH를 뒤로 보내거나, 순서 무관하게 처리
        print(f"총 {len(meetings)}개의 회의 정보 수집 및 정렬 완료.")
        return meetings

    except ftplib.error_perm as e:
        print(f"오류: '{BASE_PATH}' 경로 접근 권한 없음 또는 찾을 수 없음: {e}")
        return None
    except Exception as e:
        print(f"오류: 회의 목록 가져오기 실패: {e}")
        return None


def download_docs(ftp, all_meetings, docs_to_find, start_range_folder, end_range_folder):
    """지정된 범위의 정규 회의와 모든 AH 회의에서 문서를 검색하고 다운로드합니다."""

    if not os.path.exists(DOWNLOAD_DIR):
        print(f"로컬 다운로드 폴더 생성: '{DOWNLOAD_DIR}'")
        os.makedirs(DOWNLOAD_DIR)

    # 검색 범위 결정 (정규 회의 번호 기준)
    start_num, _ = parse_meeting_folder_name(start_range_folder)
    end_num, _ = parse_meeting_folder_name(end_range_folder)

    if start_num == -1 or end_num == -1:
        print(f"\n오류: 시작('{start_range_folder}') 또는 끝('{end_range_folder}') 폴더 이름에서 유효한 회의 번호를 추출할 수 없습니다.")
        return {} # 다운로드된 파일 정보 없음을 반환
    if start_num > end_num:
        start_num, end_num = end_num, start_num # 순서 교정
    print(f"\n문서 검색 시작: 정규 회의 {start_num}부터 {end_num}까지 + 모든 Ad-Hoc 회의")

    # 실제 검색할 회의 목록 필터링
    meetings_to_scan = []
    for meeting in all_meetings:
        if meeting.meeting_type == 'AH' and addAdhoc == True:
            # Ad-Hoc 회의는 필터링 조건(adhocFilterText)에 따라 포함됩니다.
            if adhocFilterText:
                if adhocFilterText in meeting.ftp_path:
                    meetings_to_scan.append(meeting)
            else:
                meetings_to_scan.append(meeting)

        elif meeting.meeting_type == 'Numbered' and start_num <= meeting.main_number <= end_num:
            meetings_to_scan.append(meeting) # 번호 범위 내의 정규 회의 포함


    print(f"총 {len(meetings_to_scan)}개 회의를 검색합니다.")
    print("\n--- 검색 대상 회의 목록 ---")
    if meetings_to_scan:
        for meeting in meetings_to_scan:
            print(f"  {meeting.display_name:<40} : {meeting.ftp_path}") # 이름 필드 너비 조정
    else:
        print("  (검색 대상 회의가 없습니다.)")

    found_docs_set = set() # 이미 찾은 문서 prefix 추적
    remaining_docs = set(docs_to_find) # 남은 문서 목록
    downloaded_files_by_meeting = {} # 회의별 다운로드된 파일 저장

    for meeting in meetings_to_scan:
        if not remaining_docs:
            print("\n모든 목표 문서를 찾았습니다. 검색을 조기 종료합니다.")
            break

        print(f"\n[{meeting.display_name}] 검색 중...")
        # Docs 경로 구성: ftp_path는 '/'로 끝나므로 바로 Docs 추가
        docs_path = f"{meeting.ftp_path}{DOC_SUBDIR}/"

        try:
            ftp.cwd(docs_path)
            print(f"  -> '{docs_path}' 진입")
            files_in_docs = ftp.nlst()
            print(f"  -> {len(files_in_docs)}개 파일/폴더 발견")

            docs_to_check_in_this_meeting = list(remaining_docs)

            downloaded_in_this_meeting = [] # 현재 회의에서 다운로드된 파일 목록

            for doc_prefix in docs_to_check_in_this_meeting:
                for filename in files_in_docs:
                    if filename.startswith(doc_prefix):
                        print(f"    [!] 문서 발견: {filename} (for {doc_prefix})")
                        local_filepath = os.path.join(DOWNLOAD_DIR, filename)

                        if os.path.exists(local_filepath):
                            print(f"      - 이미 로컬에 '{filename}' 파일이 존재합니다. 다운로드를 건너뜁니다.")
                            downloaded_in_this_meeting.append(local_filepath)
                        else:
                            print(f"      -> '{local_filepath}' 로 다운로드 시도...")
                            try:
                                with open(local_filepath, 'wb') as fp:
                                    # 파일 크기가 클 경우 타임아웃 발생 가능성 고려
                                    # ftp.voidcmd('TYPE I') # Binary mode 설정 (필요시)
                                    ftp.retrbinary(f'RETR {filename}', fp.write, blocksize=8192) # 블록 사이즈 지정
                                print(f"      -> 다운로드 성공!")
                                downloaded_in_this_meeting.append(local_filepath)
                            except ftplib.error_temp as ftp_temp_err:
                                print(f"      -> 다운로드 임시 오류 (재시도 가능성 있음): {ftp_temp_err}")
                                if os.path.exists(local_filepath): os.remove(local_filepath)
                            except Exception as download_e:
                                print(f"      -> 다운로드 실패: {download_e}")
                                if os.path.exists(local_filepath): os.remove(local_filepath)

                        if doc_prefix in remaining_docs:
                            remaining_docs.remove(doc_prefix)
                        found_docs_set.add(doc_prefix)
                        # break # 필요 시 같은 prefix의 다른 파일 검색 중단

            if downloaded_in_this_meeting:
                downloaded_files_by_meeting[meeting.display_name] = downloaded_in_this_meeting

            # 다음 회의 검색을 위해 기본 경로로 이동
            ftp.cwd(BASE_PATH)

        except ftplib.error_perm as e:
            if "550" in str(e):
                print(f"  -> '{DOC_SUBDIR}' 폴더 없음 또는 접근 불가 ({docs_path}). 건너뜁니다.")
            else:
                print(f"  -> '{docs_path}' 접근 중 권한 오류 발생: {e}. 건너뜁니다.")
            try:
                ftp.cwd(BASE_PATH) # 기본 경로로 복귀 시도
            except Exception as e_nav:
                print(f"오류: 기본 경로 '{BASE_PATH}'로 복귀 중 문제 발생: {e_nav}")
                return downloaded_files_by_meeting # 심각한 문제로 간주, 현재까지 다운로드된 정보 반환
        except Exception as e:
            print(f"  -> 예상치 못한 오류 발생 ({meeting.display_name}): {e}")
            try:
                ftp.cwd(BASE_PATH) # 기본 경로로 복귀 시도
            except Exception as e_nav:
                print(f"오류: 기본 경로 '{BASE_PATH}'로 복귀 중 문제 발생: {e_nav}")
                return downloaded_files_by_meeting # 심각한 문제로 간주, 현재까지 다운로드된 정보 반환

    # 최종 결과 출력
    print("\n--- 검색 완료 ---")
    print(f"총 {len(found_docs_set)}개의 문서 prefix에 해당하는 파일을 찾았습니다.")

    not_found_docs = set(docs_to_find) - found_docs_set
    if not_found_docs:
        print("\n다음 문서들은 지정된 범위(정규 회의 + 모든 AH)에서 찾지 못했습니다:")
        for doc in sorted(list(not_found_docs)):
            print(f"  - {doc}")
    else:
        print("\n모든 요청 문서를 지정된 범위 내에서 찾았습니다 (또는 다운로드 시도했습니다).")

    return downloaded_files_by_meeting


def zip_downloaded_docs(downloaded_files_by_meeting):
    """다운로드된 문서를 회의 이름으로 압축합니다."""
    if not downloaded_files_by_meeting:
        print("\n다운로드된 파일이 없습니다. 압축을 건너뜁니다.")
        return

    print("\n--- 다운로드된 문서 압축 시작 ---")
    for meeting_name, file_paths in downloaded_files_by_meeting.items():
        zip_filename = os.path.join(DOWNLOAD_DIR, f"{meeting_name}.zip")
        print(f"\n'{meeting_name}' 회의 문서를 '{zip_filename}'으로 압축 중...")
        try:
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file_path in file_paths:
                    # 압축 파일 내에 저장될 이름 (경로 제외)
                    base_name = os.path.basename(file_path)
                    zf.write(file_path, base_name)
            print(f"'{zip_filename}' 압축 완료.")
        except Exception as e:
            print(f"오류: '{zip_filename}' 압축 실패: {e}")
    print("\n--- 문서 압축 완료 ---")


# --- 메인 실행 로직 ---
if __name__ == "__main__":
    ftp = None
    start_time = datetime.now()
    print(f"스크립트 시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        print(f"{FTP_HOST}에 연결 중...")
        ftp = ftplib.FTP(FTP_HOST, timeout=60) # 타임아웃 증가 (목록 가져오기 등 시간 소요 가능)
        ftp.login()
        print("FTP 서버 연결 및 로그인 성공.")

        # 1. 회의 목록 가져오기 및 정렬
        all_meetings = get_meeting_list(ftp)

        if all_meetings:
            # 목록 확인용 (필요 시 주석 해제)
            print("\n--- 검색된 회의 목록 (정렬됨) ---")
            for m in all_meetings:
                print(f" - {m.display_name} (Type: {m.meeting_type}, SortKey: {m.sort_key})")
            print("---------------------------------")
            # sys.exit()

            # 2. 문서 다운로드 실행 및 다운로드된 파일 정보 얻기
            downloaded_files = download_docs(ftp, all_meetings, target_doc_prefixes, start_meeting_range_folder, end_meeting_range_folder)

            # 3. 다운로드된 문서 압축
            zip_downloaded_docs(downloaded_files)

    except ftplib.all_errors as e:
        print(f"\nFTP 오류 발생: {e}")
    except Exception as e:
        print(f"\n예상치 못한 오류 발생: {e}")
    finally:
        if ftp:
            try:
                ftp.quit()
                print("\nFTP 연결 종료.")
            except:
                print("\nFTP 연결 종료 중 오류 발생.")

    end_time = datetime.now()
    print(f"스크립트 종료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"총 실행 시간: {end_time - start_time}")