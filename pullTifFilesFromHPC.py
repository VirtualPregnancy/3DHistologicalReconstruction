from glob import glob
from HelperFunctions.Utilities import nameFromPath, dirMaker
import os
import multiprocessing
from multiprocessing import Process

dataHome = '/Volumes/resabi201900003-uterine-vasculature-marsden135/BoydCollection/'
samples = ['H653A_11.3']#['H1029A_8.4', 'H653A_11.3', 'H671A_18.5', 'H671B_18.5', 'H673A_7.6', 'H710B_6.1', 'H710C_6.1', 'H750A_7.0' ]


def getFiles(s, dataHome):
    print("Starting " + s)
    dirMaker('/Volumes/USB/tifFiles' + s + '/')
    os.system('scp -r ' + dataHome + s + '/3/tifFiles/* /Volumes/USB/tifFiles' + s + '/')
    print("Finished " + s)




if __name__ == "__main__":

    multiprocessing.set_start_method("fork")

    cpuNo = 1

    if cpuNo != 1:

        jobs = {}
        for s in samples:
            jobs[s] = Process(target = getFiles, args = (s, dataHome))
            jobs[s].start()

        for s in samples:
            jobs[s].join()

    else:
        for s in samples:
            getFiles(s, dataHome)