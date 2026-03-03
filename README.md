# Advanced-Capstone-Project

# 최초설정 (커밋에 수정자 찍히기 위함)
1. 이름/이메일
2. 기본 브랜치 쓰기

git config --global user.name "이름"
git config --global user.email "이메일"
git config --global init.defaultBranch main

# 시작 (원격저장소를 로컬저장소로 가져오기)

git clone 원격저장소url

# 작업 전/후 상태 확인
1. 변경사항 요약

git status

2. 커밋 로그 보기

git log --oneline --graph --decorate --all

3. 원격(origin) 확인
git remote -v

# 변경사항 저장(커밋) 흐름
1. 변경 내용 확인

git diff

2. staging 작업

git add . // 수정파일 전부 올리기

git add 파일명1, 파일명2 // 수정파일 선택 후 올리기 (이걸로 해야 안전함)

3. 커밋(스냅샷)

git commit -m "메시지"

4. git push

5. git pull

6. git fetch

# branch
1. branch 리스트

git branch

2. branch 생성/이동

git switch -c ~/branch명
혹은
git checkout -b ~/branch명

3. branch 이동

git switch branch명

4. branch 병합

git merge ~/branch명

# 되돌리기/취소 (실수 방지용)
1. add 취소 (staging에서 내리기)

git restore --staged 파일명 (전체 파일이면 파일명 자리에 .)

2. 작업파일 변경 되돌리기(로컬 수정사항 폐기)

git restore 파일명

3. 마지막 커밋 메시지 수정(푸시 전일때만 추천)

git commit --amend

# 팀플 운영에서 최소규칙 (충돌 줄이기 위함)
1. 작업 시작 전

git switch main -> git pull

2. 기능 작업

git switch -c ~

3. 커밋 후

git push -u origin ~

4. github에서 PR로 main에 합치기 (main은 최종배포 branch로 우리는 작업간 develop branch로 PR할 것)