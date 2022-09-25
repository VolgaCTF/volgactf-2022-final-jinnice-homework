FROM python:3.7.14-alpine3.16
ADD src VERSION /dist/checker/
WORKDIR /dist
RUN pip install --requirement checker/requirements.txt
CMD ["python", "-u", "checker/main.py"]
