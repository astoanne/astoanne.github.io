import requests
import sys

n = len(sys.argv)
if n!=2:
  print("只接受一个参数：推广员名称");
else:
  appid = "wx1f4c823680968cd5"
  secret = "d593fa44754c7d74097b0abecf2c70a9"

  seller = sys.argv[1]
  filename = seller+'-专属推广码.png'

  tokenResponse = requests.get("https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid="+appid+"&secret="+secret)
  accessToken = tokenResponse.json()['access_token']
  print(accessToken)
  payload =  {
  "path":"pages/index/index?seller="+seller,
  "width":430
  }
  qrCodeResponse = requests.post("https://api.weixin.qq.com/wxa/getwxacode?access_token="+accessToken,json=payload)
  if qrCodeResponse.status_code == 200:
    with open(filename, 'wb') as f:
      f.write(qrCodeResponse.content)
