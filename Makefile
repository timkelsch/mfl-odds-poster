.PHONY: build

AWS_REGION=us-east-1
AWS_ACCOUNT=$(shell aws sts get-caller-identity | jq -r '.Account')
CODE_DIR=mfl-odds
VERSION=$(shell aws ecr get-login-password --region us-east-1 | docker login --username AWS \
  --password-stdin 287140326780.dkr.ecr.us-east-1.amazonaws.com 2>&1 > /dev/null && aws ecr describe-images \
  --region us-east-1 --output json --repository-name mfl-odds \
  --query 'sort_by(imageDetails,& imagePushedAt)[-1].imageTags[0]' | jq . -r)
IMAGE_URI=${AWS_ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com/mfl-odds:${VERSION}

FUNCTION_NAME=$(shell aws lambda list-functions --output json | jq -r '.Functions[] | \
  select(.FunctionName | startswith("mfl-odds")) | .FunctionName')
STACK_NAME=mfl-odds
TEMPLATE_FILE=file://mfl-odds.yaml
  
export FUNCTION_NAME
export AWS_REGION
export AWS_ACCOUNT
 
createstack:
	aws cloudformation create-stack --stack-name ${STACK_NAME} --template-body ${TEMPLATE_FILE} \
		--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM --region ${AWS_REGION}

updatestack:
	aws cloudformation update-stack --stack-name ${STACK_NAME} --template-body ${TEMPLATE_FILE} \
		--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM --region ${AWS_REGION}

deletestack:
	aws cloudformation delete-stack --stack-name ${STACK_NAME} --region ${AWS_REGION}

test:
	cd ${CODE_DIR} && go test -cover

push:
	./push.sh

updatelambda:
	aws lambda update-function-code --function-name ${FUNCTION_NAME} \
		--image-uri ${IMAGE_URI} --publish --region ${AWS_REGION}

build:
	docker build --platform linux/amd64 -t mfl-scoring-image:mod .

val:
	aws cloudformation validate-template --template-body ${TEMPLATE_FILE}