# Advanced-Capstone-Project

# 최초설정 (커밋에 수정자 찍히기 위함)
- 이름/이메일
- 기본 브랜치 쓰기

git config --global user.name "이름"
git config --global user.email "이메일"
git config --global init.defaultBranch main

# 시작 (원격저장소를 로컬저장소로 가져오기)

git clone 원격저장소url

# 작업 전/후 상태 확인
- 변경사항 요약

git status

- 커밋 로그 보기

git log --oneline --graph --decorate --all

- 원격(origin) 확인

git remote -v

# 작업 간 규칙

본인이 담당한 파일만 건드릴 것. 만약 기능 구현 간 부득이하게 다른 팀원 파일을 건드려야할 땐,
꼭 작업 중인지 물어보고 수정할 것 (동시작업 시 병합 후 오류발생함. 복구하는 작업이 매우 피곤)

# 작업 간 알아야할 것

항상 작업에 들어가기 전 로컬저장소 최신화 필요
우리는 main(최종배포용) 말고 develop 브랜치 생성 후 작업할거임 (main은 혹시나 해결못할 충돌 발생 시 백업하기 위한 브랜치)

만약, 내가 맡은 기능에 대해서 작업을 들어갈거다?
그럼 팀원 누군가 develop에 기능을 추가해뒀을 수도 있으니 충돌예방을 위해 git pull 로 최신화 해준 뒤
작업할 브랜치 만들어서 작업할 것

# 이슈화 작업
각자 맡은 파트에 맡게 본인 작업 issue 를 생성 후 issue #number 에 맞는 브랜치까지 생성할 것

ex)  [FEATURE] login 추가 issue를 생성하면 issue number가 부여됨 #31 이런식으로

그리고 브랜치명은 각 이슈에 맞게 feature/31 이렇게 생성할 것

# develop 브랜치 최신버전을 다시 가져오고 싶을 때

1. 현재 상태 확인
git status
2. 로컬 변경사항 (모두) 취소 [수정한 파일들 원래대로 되돌리는 과정]
- git restore ~/example1.c  
- git restore .
→ restore 커맨드는 local에서만 변경사항을 취소하는 것 (github 영향 X)
3. untracked 파일 삭제 (새로만든 파일들) [git이 추적 안하는 새파일/폴더 삭제]
git clean -fd
4. 최신 develop 가져오기
git pull origin develop
5. 다시 상태 확인
git status

# 더 강력한 버전 (이미 commit을 해버린 상황일 때 강제복구)

1. git status
2. git reset —hard origin/develop [로컬 commit도 전부 취소해버림]
3. git clean -fd
4. git pull origin develop

