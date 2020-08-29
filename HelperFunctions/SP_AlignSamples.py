'''

this script takes feat, bound and segsection information and rotates them to minimise 
the error between slices

'''
if __name__ == "__main__":
    from Utilities import *
    from SP_SampleAnnotator import featChangePoint
else:
    from HelperFunctions.Utilities import *
    from HelperFunctions.SP_SampleAnnotator import featChangePoint
import numpy as np
import tifffile as tifi
import cv2
from scipy.optimize import minimize
from random import randint
from math import ceil
from glob import glob
import multiprocessing
from multiprocessing import Process, Queue
from copy import deepcopy

# object which contains the reference and target positions between a single matching pair
class sampleFeatures:
    def __init__(self, ref = None, tar = None, fit = None, shape = None):
        self.ref = ref
        self.tar = tar
        self.fit = fit


tifLevels = [20, 10, 5, 2.5, 1.25, 0.625, 0.3125, 0.15625]

# NOTE this should include a function where if there are args in the .feat and .bound 
# files (ie the size of the original image it came from) then re-shape to the new size

'''

TODO
    - make it work as part of the automatic workflow script taking the .feat files
    outputted from FeatFinder 

'''

def align(data, name = '', size = 0, saving = True):

    # This function will take the extracted sample tif file at the set resolution and 
    # translate and rotate them to minimise the error between slices
    # co-ordinates of the key features on that image for alignment
    # Inputs:   (data), directories of the tif files of interest
    #           (featDir), directory of the features
    # Outputs:  (), extracts the tissue sample from the slide and aligns them by 
    #           their identified featues

    # get the file of the features information 
    src = data + str(size)
    dataSegmented = src + '/masked/'     
    alignedSamples = src + '/alignedSamples/'
    segInfo = src+ '/info/'

    # get the sample slices of the specimen to be processed
    samples = sorted(nameFromPath(glob(dataSegmented + "*.tif"), 3))

    # get affine transformation information of the features for optimal fitting
    # NOTE this has to be sequential
    shiftFeatures(samples, segInfo)
    
    # serial transformation
    for spec in samples:
        transformSamples(dataSegmented, segInfo, alignedSamples, spec, size, saving = False)

    # my attempt at parallelising this part of the process. Unfortunately it doesn't work 
    # because the cv2.warpAffine function is objectivePolar fails for AN UNKNOWN REASON
    # when finding the new matrix on the second feature.... unknown specifically but 
    # issues with opencv and multiprocessing are known. 
    '''
    jobs = {}
    for spec in specimens:
        jobs[spec] = Process(target=transformSamples, args = (dataSegmented, segInfo, alignedSamples, spec, size, saving)) 
        jobs[spec].start()

    for spec in specimens:
        jobs[spec].join()
    '''
    print('Alignment complete')

def shiftFeatures(featNames, src):

    # Function takes the images and translation information and adjusts the images to be aligned and returns the translation vectors used
    # Inputs:   (featNames), the samples being aligned
    #           (src)
    #           (alignedSamples)
    # Outputs:  (translateNet), the translation information to be applied per image
    #           (rotateNet), the rotation information to be applied per image

    # load the identified features
    # NOTE it is loaded twice because the dictionary memories are way to linked and 
    # they keep getting altered somewhere?!?!
    feats = {}
    featRef = {}
    featTar = {}
    for f in featNames:
        # featsMaster[f] = txtToDict(src + f + ".feat", float)[0]
        # feats[f] = txtToDict(src + f + ".feat", float)[0]
        try: 
            featTar[f] = txtToDict(src + f + ".tarfeat", float)
        except: pass
        try: 
            featRef[f] = txtToDict(src + f + ".reffeat", float)
        except: featRef[f] = featTar[f]     # the last feature will never be fit so this 
                                            # this is essentially a junk data allocated 
                                            # only so that the whole script will run error 
                                            # free (main issue is carry through transformation
                                            # of features)                     
                                            
    # store the affine transformations
    translateNet = {}
    rotateNet = {}

    # initialise the first sample with no transformation
    translateNet[featNames[0]] = np.array([0, 0])
    rotateNet[featNames[0]] = [0, 0, 0]
    featsO = sampleFeatures()

    # perform transformations on neighbouring slices and build them up as you go
    for rF, tF in zip(featRef, featTar):

        # print("Ref0: " + str(featRef[rF]['feat_0']) + " Tar0: " + str(featTar[tF]['feat_0']))
        
        '''
        # select neighbouring features to process
        featsO = {}     # feats optimum, at this initialisation they are naive but they will progressively converge 
        for tF in featNames[i:i+2]:
            featsO[tF] = feats[tF]
        '''

        # get the features to align
        # NOTE atm whichever dictionary assignment is first comes linked to featsMod
        # so they both become changed but ONLY the first one..... ?????
        featsO.ref = deepcopy(featRef[rF][0])
        featsO.tar = deepcopy(featTar[tF][0])
        featsO.fit = featTar[tF][1]['fit']

        # set the initial attempt positional ranges to remove features in the case of 
        # refitting attempts
        atmpR = 1
        atmp = 0
        lastFt = []
        n = 0
        
        print("Shifting " + tF + " features")
        # -------- CREATE THE MOST OPTIMISED POSSIBLE FIT OF 
        #       FEATURES POSSIBLE, SAVE THE NEW FEATURES AND THEIR 
        #                       TRANSFORMATIONS --------
        while featsO.fit is False:

            # !! Every time the loop starts here, it is trying to fit a NEW set of features !!

            # featMod, the pair of features being fit
            # featO, the pair of features to be fit BEFORE transformations have begun
            # feattmp, the features that have been modified in a single fitting procedure
            #   temporarily stored until they are assigned

            # declare variables for error checking and iteration counting
            errN = 1e6
            errorC = 1e6
            errCnt = 0  
            errorStore = np.ones(3) * 1e6
            translateSum = np.zeros(2).astype(float)
            featsMod = deepcopy(featsO)
            refit = False
            manualFit = False
            
            while True:        

                # !! Every time the loop starts here, it is OPTIMISING the fit of the CURRENT features !!
                
                # use the previous error for the next calculation
                errO = errN
                errorCc = errorC

                # get the translation vector
                translation, feattmp, err = translatePoints(featsMod, bestfeatalign = False)
                
                # keep track of a temporary translation
                #print("ts = " + str(translateSum))
                translateSum += translation
                #print("te = " + str(translateSum))

                # print(translation[tF]) # --> the last optimal change in location is the WRONG shift
                # store the accumulative translation vectors 

                # find the optimum rotational adjustment and produce modified feats
                _, feattmp, errN, centre = rotatePoints(feattmp, bestfeatalign = False, plot = False)

                # print("     Fit " + str(n) + " Error = " + str(errN))

                # change in errors between iterations, using two errors
                errorC = errO - errN

                # store the last n changes in error
                errorStore = np.insert(errorStore, 0, errN)
                errorStore = np.delete(errorStore, -1)
                
                # sometimes the calcultions get stuck, ossiclating between two errrors
                # of the same magnitude but opposite sign
                if errorC + errorCc == 0:
                    errCnt += 1     # count the number of times these ossiclations occur

                # conditions to finish the fitting proceduce
                #   the error of fitting = 0
                #   a turning point has been detected and error is increasing
                if errN == 0:
                    print("     Fitting successful, err/feat = " + str(errN)) 
                    featsMod = feattmp      # this set of feats are the ones to use

                # positions have converged on the optimum and the error is acceptable
                elif np.round(np.sum(np.diff(errorStore)), 2) <= 0:
                    # if the final error is below a threshold, it is complete
                    # but use the previously fit features
                    if errO < 1e2:
                        print("     Fitting converged, attempt " + str(n) + ", err/feat = " + str(errO))
                        break

                    # with the current features, if they are not providing a good match
                    # then delet them from the dictionary. The features are ordered by 
                    # the distance of the descriptor with feat_0 the best fit.
                    else:
                        # print("     Modifying feat, err/feat = " + str(errO))
                        # denseMatrixViewer([featsMod[rF], featsMod[tF], centre[tF]], True)
                        
                        # there have to be at least 3 points left to enable good fitting practice
                        # if there aren't going to be 3 left do a manual fitting process
                        if len(featsO.tar) < 3: 
                            manualFit = True

                        # if there are only 3 points left and the fitting hasn't converged, 
                        # then remove a larger range of points
                        elif atmp > len(featsO.tar):
                            atmpR += 1
                            atmp = 0

                        # modify the availabe features to create a better alignment
                        featsO.ref = deepcopy(featRef[rF][0])
                        featsO.tar = deepcopy(featTar[tF][0])
                        refit = True
                        lastFt = np.flip(list(featsO.tar.keys()))[atmp:atmp+atmpR]
                        # print("         Removed: " + str(lastFt))
                        for lF in lastFt:
                            del featsO.tar[lF]
                            del featsO.ref[lF]
                        atmp += 1
                        break

                # if there are only 3 features remaining for the fitting process
                # then it will require manual fitting
                elif errCnt > 10 or n > 200:
                    refit = True
                    break

                # update the current features being modified 
                featsMod = feattmp

                # count the number of fits done
                n += 1
                    
            # -------- PERFORM A NEW FITTING PROCEDURE WITH MODIFIED FEATURES --------

            # if there is no possible combination of features that can fit the samples, 
            # manually annotate new one
            if manualFit:

                print("\n\n!! ---- FITTING PROCEDUCE DID NOT CONVERGE  ---- !!\n\n")
                print("     Refitting, err = " + str(errN))

                denseMatrixViewer([dictToArray(featsMod.ref), dictToArray(featsMod.tar), centre], True)

                # change the original positions used
                annoRef, annoTar = featChangePoint(regionOfPath(src, 2), rF, tF, ts = 4)

                _, commonFeats = uniqueKeys([annoRef, featRef[rF][0]])
                
                # go through all the annotations and see if there have actually been any changes made
                same = True
                for cf in commonFeats:
                    # check if any of the annotations have changed
                    if (annoRef[cf] != featRef[rF][0][cf]).all() or (annoTar[cf] != featTar[tF][0][cf]).all():
                        same = False 
                        break

                # if there have been no changes then break the fitting process and accept
                # the fitting proceduce as final
                if same:
                    break

                # update the master dictionary as these are the new features saved
                featRef[rF][0] = annoRef
                featTar[tF][0] = annoTar

                # updated the featO features for a new fitting procedure based on these new
                # modified features
                featsO.ref = annoRef
                featsO.tar = annoTar
                atmpe = 1
            
            # if there are enough feature available but alignment didn't converge to 
            # an error low enough, iterate through
            elif refit: 
                continue

            # if a suitable alignment has been found then progress
            else:
                # replace the features that were found with the ones that 
                # allowed for this fitting
                featRefFinal = deepcopy(featRef[rF][0])
                featTarFinal = deepcopy(featTar[tF][0])
                for lF in lastFt:
                    del featRefFinal[lF]
                    del featTarFinal[lF]

                # replace the features in the matched folder so that you dont' have to constantly 
                # refit the features everytime you run this script
                dictToTxt(featRefFinal, src + rF + ".reffeat", fit = True)
                dictToTxt(featTarFinal, src + tF + ".tarfeat", fit = True)
                break

        # -------- CREATE THE SINGLE TRANSLATION AND ROTATION FILES --------

        # if the file was already fit then don't save any information
        if featsO.fit:
            print("     " + tF + " is already fitted")
            translateNet[tF] = np.array([0, 0])
            rotateNet[tF] = [0, 0, 0]

        else:
            # replicate the whole fitting proceduce in a single go to be applied to the 
            # images later on
            featToMatch = sampleFeatures()
            featToMatch.ref = deepcopy(featsMod.tar)       # get the fitted feature (ref)
            featToMatch.tar = deepcopy(featsO.tar)        # get the previous position of it

            # translation, featToMatch, err = translatePoints(featToMatch, True)

            # apply ONLY the translation transformations to the original features so that the 
            # adjustments are made to the optimised feature positions
            for f in featToMatch.tar:
                # print("Orig: " + str(featsMaster['H653A_09_1'][f]))
                featToMatch.tar[f] -= translateSum
                
            translateNet[tF] = translateSum

            # perform a single rotational fitting procedure
            # NOTE add recursive feat updater
            rotated = 10
            rotateSum = 0
            n = 0

            # view the final points before rotating VS the optimised points
            # denseMatrixViewer([dictToArray(featToMatch[tF]), dictToArray(featsMod[tF]), centre[tF]], True)

            # continue fitting until convergence with the already fitted results
            while abs(errN) > 1e-8:
                rotationAdjustment, featToMatch, errN, cent = rotatePoints(featToMatch, bestfeatalign = False, plot = False, centre = centre)
                rotated = rotationAdjustment
                rotateSum += rotationAdjustment
                # print("Fit: " + str(n) + " FINAL FITTING: " + str(errN))
                n += 1

            # rotate the same transofmratino to the next set of reference features
            for f in featRef[tF][0]: 
                featRef[tF][0][f] -= translateSum      
            featRef[tF][0] = objectivePolar(rotateSum, centre, False, featRef[tF][0]) 

            # pass the rotational degree and the centre of rotations
            rotateNet[tF] = [rotateSum, centre[0], centre[1]]  
            # denseMatrixViewer([featsMod.ref, featsMod.tar, centre], True)

            # save the tif shapes, translation and rotation information
            dictToTxt(translateNet, src + "all.translated")
            dictToTxt(rotateNet, src + "all.rotated")

def transformSamples(segSamples, segInfo, dest, spec, size, saving):
    # this function takes the affine transformation information and applies it to the samples
    # Inputs:   (src), directories of the segmented samples
    #           (dest), directories to save the aligned samples
    #           (spec), sample being processed
    #           (saving), boolean whether to save new info
    # Outputs   (), saves an image of the tissue with the necessary padding to ensure all images are the same size and roughly aligned if saving is True

    def adjustPos(infoE, dest, spec, maxPos, translateNet, w, shapeR, t, centre = None):

        # this funciton adjusts the position of features in the txt files and resaves them
        # in the destination location
        # Inputs:   (s), directory of the specimens features to adjust
        #           (dest), directory to save new text file
        #           (spec), sample name
        #           (maxPos), field adjustment size
        #           (translateNet), translations of the sample
        #           (rotateNet), rotations of the sample
        #           (shapeR), the scale factor for the modified images
        #           (t), type of file
        #           (centre), position of the centre, if not given will be calculated from input features
        # Outputs:  (), saves the positions with the transformation 
        #           (centre), if the centre is not given then it is to be found from these calculations


        # adjust the positions based on the fitting process
        for f in infoE:
            infoE[f] = (infoE[f] - translateNet) * shapeR
        infoE = objectivePolar(w, centre, False, infoE) 

        # adjust the positions based on the whole image adjustment
        
        for f in infoE:
            infoE[f] += np.array(maxPos)  
        
        # save the info
        dictToTxt(infoE, dest + spec + "." + t)     # from the info in the txt file, rename
        return(infoE)
        
    
    segmentdir = segSamples + spec + ".tif"
    refdir = segInfo + spec + ".reffeat"
    tardir = segInfo + spec + ".tarfeat"
    tifShapesdir = segInfo + "all.tifshape"
    jpgShapesdir = segInfo + "all.jpgshape"
    translateNetdir = segInfo + "all.translated"
    rotateNetdir = segInfo + "all.rotated"

    # load the whole specimen info
    translateNet = txtToDict(translateNetdir, float)[0]
    tifShapes = txtToDict(tifShapesdir, int)[0]
    jpgShapes = txtToDict(jpgShapesdir, int)[0]
    rotateNet = txtToDict(rotateNetdir, float)[0]
    specInfo = {}

    # initialise the end position of the tif image to be cropped
    posE = 0

    try: featR = txtToDict(refdir, float); specInfo['reffeat'] = featR[0]
    except: pass

    try: featT = txtToDict(tardir, float); specInfo['tarfeat'] = featT[0]
    except: pass

    sample = nameFromPath(segmentdir, 3)

    # get the size of jpeg version of the image, some tedious formatting changes to make into
    # an np.array
    jpegSize = jpgShapes[sample]
    
    # get the shapes of the jpeg image and original tif and find the ratio fo their sizes
    shapeO = tifShapes[sample]
    shapeR = np.round((shapeO / jpegSize)[0], 1)

    # get the measure of the amount of shift to create the 'platform' which all the images are saved to
    ss = (np.ceil(dictToArray(translateNet, int) * shapeR)).astype(int)     # scale up for the 40% reduction in tif2pdf
    maxSx = np.max(ss[:, 0])
    maxSy = np.max(ss[:, 1])
    minSx = np.min(ss[:, 0])
    minSy = np.min(ss[:, 1]) 
    maxPos = (maxSx, maxSy)

    # get the anlge and centre of rotation used to align the samples
    w = -rotateNet[sample][0]
    centre = rotateNet[sample][1:] * shapeR

    # make destinate directory
    dirMaker(dest)

    # ---------- apply the transformations onto the images ----------

    # adjust the translations of each image and save the new images with the adjustment
    # for spec in src:

    # process for feats, bound and segsections. NOTE segsections not always present so 
    # error handling incorporated

    for t in specInfo:
        # adjust all the points
        specInfo[t] = adjustPos(specInfo[t], dest, sample, maxPos, translateNet[sample], w, shapeR, t, centre)

    # translate the image  
    
    # get the maximum dimensions of all the tif images (NOT the jpeg images)
    tsa = dictToArray(tifShapes, int)

    my, mx, _ = (np.max(tsa, axis = 0)).astype(int)

    # get the dims of the total field size to be created for all the images stored
    yF, xF, cF = (my + maxSy - minSy, mx + maxSx - minSx, 3)       # NOTE this will always be slightly larger than necessary because to work it    
                                                                    # out precisely I would have to know what the max displacement + size of the img
                                                                    # is... this is over-estimating the size needed but is much simpler
    xp = int(maxSx - np.floor(translateNet[sample][0]) * shapeR)
    yp = int(maxSy - np.floor(translateNet[sample][1]) * shapeR)

    # Load the entire image
    field = cv2.imread(segmentdir)

    # get the section of the image 
    fy, fx, fc = field.shape

    newField = np.zeros([yF, xF, cF]).astype(np.uint8)      # empty matrix for ALL the images
    newField[yp:(yp+fy), xp:(xp+fx), :] += field


    # apply the rotational transformation to the image
    centre = centre + maxPos

    rot = cv2.getRotationMatrix2D(tuple(centre), -float(w), 1)
    warped = cv2.warpAffine(newField, rot, (xF, yF))

    print("done translation of " + sample)

    # NOTE change the inputs to a single large dictionary
    plotPoints(dest + sample + '_alignedAnnotatedUpdated.jpg', warped, centre, specInfo)

    # this takes a while so optional
    if saving:
        cv2.imwrite(dest + sample + '.tif', warped)                               # saves the adjusted image at full resolution 
        cv2.imwrite(dest + sample + '.png', cv2.resize(warped, (int(warped.shape[1]*0.2), int(warped.shape[0]*0.2))))

def translatePoints(feats, bestfeatalign = False):

    # get the shift of each frame
    # Inputs:   (feats), dictionary of each feature
    #           (bestfeatalign), boolean if true then will align all the samples
    #           based off a single point, rather than the mean of all
    # Outputs:  (shiftStore), translation applied
    #           (feats), the features after translation
    #           (err), squred error of the target and reference features
    
    featsMod = deepcopy(feats)
    shiftStore = {}
    ref = feats.ref
    tar = feats.tar

    [tarP, refP], featkeys = uniqueKeys([tar, ref])

    if bestfeatalign:
        refP = {}
        tarP = {}
        refP[featkeys[0]] = ref[featkeys[0]]
        tarP[featkeys[0]] = tar[featkeys[0]]

    # get the shift needed and store
    res = minimize(objectiveCartesian, (0, 0), args=(refP, tarP), method = 'Nelder-Mead', tol = 1e-6)
    shift = res.x
    err = objectiveCartesian(res.x, tarP, refP)

    # modify the target positions
    tarM = {}
    for t in tar.keys():
        tarM[t] = tar[t] - shift

    featsMod.tar = tarM

    return(shift, featsMod, err)

def rotatePoints(feats, tol = 1e-6, bestfeatalign = False, plot = False, centre = None):

    # get the rotations of each frame
    # Inputs:   (feats), dictionary of each feature
    # Outputs:  (rotationStore), affine rotation matrix to rotate the IMAGE --> NOTE 
    #                       rotating the image is NOT the same as the features and this doesn't 
    #                       quite work propertly for some reason...
    #           (featsmod), features after rotation
    
    featsMod = deepcopy(feats)
    ref = feats.ref
    tar = feats.tar

    # get the common features
    [tarP, refP], commonFeat = uniqueKeys([tar, ref])

    # if doing best align, use the first feature as the centre of rotation,
    # otherwise use the mean of all the features
    if centre is None:
        if bestfeatalign:
            centre = tarP[commonFeat[0]]
        else:
            centre = findCentre(tarP)
    
    # get the shift needed and store
    res = minimize(objectivePolar, -5.0, args=(centre, True, tarP, refP), method = 'Nelder-Mead', tol = tol) # NOTE create bounds on the rotation
    tarM = objectivePolar(res.x, centre, False, tar, refP, plot)   # get the transformed features and re-assign as the ref
    rotationStore = float(res.x)

    # return the average error per point
    err = res.fun / len(tarP)

    # reassign this as the new feature
    featsMod.tar = tarM
    
    if plot: denseMatrixViewer([dictToArray(refN), dictToArray(refP), centre], True)

    return(rotationStore, featsMod, err, centre)

def plotPoints(dir, imgO, cen, points):

    # plot circles on annotated points
    # Inputs:   (dir), either a directory (in which case load the image) or the numpy array of the image
    #           (imgO), image directory
    #           (cen), rotational centre
    #           (points), dictionary or array of points which refer to the co-ordinates on the image
    # Outputs:  (), saves downsampled jpg image with the points annotated

    # load the image
    if type(imgO) is str:
            imgO = cv2.imread(imgO)

    img = imgO.copy()
    colours = [(0, 255, 0), (0, 0, 255), (0, 255, 255), (255, 255, 255)]
    sizes = [1, 0.8, 0.6, 0.4]

    si = 50

    # for each set of points add to the image
    for n, pf in enumerate(points):

        point = points[pf]

        if type(point) is dict:
            point = dictToArray(point)

        for p in point:       # use the target keys in case there are features not common to the previous original 
            pos = tuple(np.round(p).astype(int))
            img = cv2.circle(img, pos, int(si * sizes[n]), tuple(colours[n]), int(si * sizes[n]/2)) 
        
    # plot of the rotation as well using opposite colours
    cen = cen.astype(int)
    # img = cv2.circle(img, tuple(findCentre(points)), si, (0, 255, 0), si) 
    img = cv2.circle(img, tuple(cen), int(si * sizes[n] * 0.8), (255, 0, 0), int(si * sizes[n] * 0.8/2)) 

    # resize the image
    x, y, c = img.shape
    imgResize = cv2.resize(img, (2000, int(2000 * x/y)))

    cv2.imwrite(dir, imgResize, [cv2.IMWRITE_JPEG_QUALITY, 80])

    return (imgResize)

def objectiveCartesian(pos, *args):

    # this function is the error function of x and y translations to minimise error 
    # between reference and target feature co-ordinates
    # Inputs:   (pos), translational vector to optimise
    #           (args), dictionary of the reference and target co-ordinates to fit for
    # Outputs:  (err), the squarred error of vectors given the shift pos

    ref = args[0]   # the first argument is ALWAYS the reference
    tar = args[1]   # the second argument is ALWAYS the target

    tarA = dictToArray(tar, float)
    refA = dictToArray(ref, float)

    # error calcuation
    err = np.sum((refA + pos - tarA)**2)
    # print(str(round(pos[0])) + ", " + str(round(pos[1])) + " evaluated with " + str(err) + " error score")

    return(err)      

def objectivePolar(w, centre, *args):

    # this function is the error function of rotations to minimise error 
    # between reference and target feature co-ordinates    
    # Inputs:   (w), angular translation to optimise
    #           (centre), optional to specify the centre which points are being rotated around
    #           (args), dictionary of the reference and target co-ordinates to fit for 
    #                   boolean on whether to return the error (for optimisation) or rot (for evaluation)
    #                   (minimising), if true then performing optimal fitting of target onto 
    #                   reference. If false then it is just rotating the points given to it as the target
    # Outputs:  (err), the squarred error of vectors given the shift pos
    #           (rot), the affine transform matrix used to (works on images)
    #           (tar), the new features after transforming

    minimising = args[0]
    tar = args[1]   # the second argument is ALWAYS the target, ie the one that is being fitted onto the reference
    if minimising:
        ref = args[2]   # the first argument is ALWAYS the reference, ie the one that isn't rotating
    
    try:
        plotting = args[3]
    except:
        plotting = False

    if type(w) is np.ndarray:
        w = w[0]

    
    tarN = {}

    # this will shrink the matrices made and all the feature co-ordinates by this 
    # factor in order to reduce the time taken to compute
    # NOTE the more it is scaled the more innacuracies are created, however appears 
    # that it is pretty accurate with a 10 scaling but is also acceptably fast
    scale = 1

    tarA = dictToArray(tar, float)
    
    # if the centre is not specified, find it from the target points
    if np.sum(centre == None) == 1:
        centre = findCentre(tarA)       # this is the mean of all the features

    # find the centre of the target from the annotated points
    tarA = (tarA/scale).astype(float)
    centre = (centre/scale).astype(float)

    Xmax = int(tarA[:, 0].max())
    Xmin = int(tarA[:, 0].min())
    Ymax = int(tarA[:, 1].max())
    Ymin = int(tarA[:, 1].min())

    y, x = (Ymax - Ymin, Xmax - Xmin)


    # debugging stuff --> shows that the rotational transformation is correct on the features
    # so it would suggest that the centre point on the image is not being matched up well
    
    # create an array to contain all the points found and rotated
    m = 1
    plotting = False

    # process per target feature
    tarNames = list(tar)

    # adjust the position of the features by w degrees
    # NOTE this is being processed per point instead of all at once because of the fact that rotating points causes
    # a 'blurring' of the new point and to identify what the new point is from this 'blur', we have to be able 
    # to recognise each point. I have decided it is simpler to identify each point by processing each one individually, 
    # rather than doing some kind of k-means clustering rubbish etc. 
    for n in range(len(tarNames)):

        feat = tarNames[n]

        # find the feature relative to the centre
        featPos = tarA[n, :] - centre

        # calculate the distance from the centre
        hyp = np.sqrt(np.sum((featPos)**2))

        # if there is no length (ie rotating on the point of interest)
        # just skip
        if hyp == 0:
            tarN[feat] = tarA[n, :]
            continue

        # get the angle of the point relative to the horiztonal
        angle = findangle(tarA[n, :], centre)
        anglen = angle + w*np.pi/180

        # calculate the new position
        opp = hyp * np.sin(anglen)
        adj = hyp * np.cos(anglen)

        newfeatPos = np.array([opp, adj] * scale).astype(float) + centre

        # if the features were inversed, un-inverse

        tarN[feat] = newfeatPos


        # if plotting: denseMatrixViewer([tarA[n], tarN[i], centre])

    
    if plotting: denseMatrixViewer([tarA, dictToArray(tarN), centre])

    # print(dictToArray(tarN))
    # print(tarA)

    # print("w = " + str(w))
    # if optimising, return the error. 
    # if not optimising, return the affine matrix used for the transform
    if minimising:

        tarNa = dictToArray(tarN, float)
        refa = dictToArray(ref, float)
        err = np.sum((tarNa - refa)**2)
        # error calculation
        # print("     err = " + str(err))
        return(err)  

    else:
        return(tarN)

def findCentre(pos, typeV = float):

    # find the mean of an array of points which represent the x and y positions
    # Inputs:   (pos), array
    # Outputs:  (centre), the mean of the x and y points (rounded and as an int)

    if type(pos) == dict:
        pos = dictToArray(pos, float)

    centre = np.array([np.mean(pos[:, 0]), np.mean(pos[:, 1])]).astype(typeV)

    return(centre)

if __name__ == "__main__":

    # dataHome is where all the directories created for information are stored 
    dataSource = '/Volumes/USB/Testing1/'
    dataSource = '/Volumes/USB/H653/'
    dataSource = '/Volumes/USB/H673A_7.6/'
    dataSource = '/Volumes/USB/H710C_6.1/'
    dataSource = '/Volumes/Storage/H653A_11.3new/'
    dataSource = '/Volumes/USB/H653A_11.3/'
    dataSource = '/Volumes/USB/H710C_6.1/'


    # dataTrain = dataHome + 'FeatureID/'
    name = ''
    size = 3

    align(dataSource, name, size, True)
