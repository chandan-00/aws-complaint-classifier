FROM public.ecr.aws/lambda/python:3.12

COPY lambda/inference/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY model/model_int8.onnx   ${LAMBDA_TASK_ROOT}/model/model_int8.onnx
COPY model/tokenizer.json    ${LAMBDA_TASK_ROOT}/model/tokenizer.json
COPY model/metadata.json     ${LAMBDA_TASK_ROOT}/model/metadata.json

COPY lambda/inference/app.py ${LAMBDA_TASK_ROOT}/app.py

CMD ["app.handler"]
