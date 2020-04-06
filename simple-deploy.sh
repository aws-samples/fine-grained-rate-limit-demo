npm install cdk@1.30.0 -g -y --quiet --no-progress
pip install -r requirements.txt --quiet
cwd=$(pwd)
cd $cwd/lambda
pip install -r requirements.txt -t .dist
cd $cwd/lambda/.dist
rm lambda.zip || true
cd $cwd/lambda/
zip -r9 .dist/lambda.zip * -x ".dist"
cd $cwd
cdk synth rate-limit-demo
cdk deploy rate-limit-demo "$*"