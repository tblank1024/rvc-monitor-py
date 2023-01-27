import json, pprint
import ruamel.yaml as yaml

try:
    datafile = open("datafile.txt", "r")
except:
    print("Can't open datafile.txt")
    exit()

line = datafile.readline()
summary = {}
while line:
    #all input comes just from a file
    try:
        myresult = json.loads(line)
        summary.update({myresult["name"]: myresult})
    except:
        datafile.close()
        print('file format error closing')
        exit()
    line = datafile.readline()
datafile.close()

newsummary = pprint.pformat(summary,width=120)
newsummary = newsummary.replace("\'","\"")
print(newsummary)