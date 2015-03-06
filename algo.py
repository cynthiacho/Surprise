from scipy.stats import rv_discrete
from scipy.spatial.distance import cosine
import numpy as np
import random as rd
import pickle
import time
import os

import common as cmn

class Algo:
    """Abstract Algo class where is defined the basic behaviour of a recomender
    algorithm"""
    def __init__(self, rm, ur=None, mr=None, movieBased=False, withDump=True):

        # handle multiple inheritance of algorithms...
        if hasattr(self, 'initialized'):
            return
        self.initialized = True

        # whether the algo will be based on users
        # if the algo is user based, x denotes a user and y a movie
        # if the algo is movie based, x denotes a movie and y a user
        self.ub = not movieBased 

        if self.ub:
            self.rm = rm.T # we take the transpose of the rating matrix
            self.lastXi = cmn.lastUi
            self.lastYi = cmn.lastMi
            self.xr = ur
            self.yr = mr
        else:
            self.lastXi = cmn.lastMi
            self.lastYi = cmn.lastUi
            self.rm = rm
            self.xr = mr
            self.yr = ur

        self.est = 0 # set by the estimate method of the child classes
        self.preds = [] # list of (estimation, r0) so far
        self.nImp = 0 # number of impossible predictions
        self.mae = self.rmse = self.accRate = 0 # statistics

        self.withDump = withDump
        self.infos = {}
        self.infos['name'] = 'undefined'
        self.infos['params'] = {} 
        self.infos['params']['based on '] = 'users' if self.ub else 'movies'
        self.infos['ests'] = [] 

    def dumpInfos(self):
        if not self.withDump:
            return
        if not os.path.exists('./dumps'):
            os.makedirs('./dumps')
        
        date = time.strftime('%y%m%d-%H:%M:%S', time.localtime())
        pickle.dump(self.infos, open('dumps/' + self.infos['name'] + date, 'wb'))

    def getx0y0(self, u0, m0):
        """return x0 and y0 based on the self.ub variable (see constructor)"""
        if self.ub:
            return u0, m0
        else:
            return m0, u0

    def updatePreds(self, r0, output=True):
        """update preds list and print some info if required
        
        should be called right after the estimate method
        """
        if output:
            if self.est == 0:
                print(cmn.Col.FAIL + 'Impossible to predict' + cmn.Col.ENDC)
            if self.est == r0:
                print(cmn.Col.OKGREEN + 'OK' + cmn.Col.ENDC)
            else:
                print(cmn.Col.FAIL + 'KO ' + cmn.Col.ENDC + str(self.est))

        if self.est == 0:
            self.nImp += 1
            self.est = 3 # default value

        self.preds.append((self.est, r0))
        

    def makeStats(self, output=True):
        """compute some statistics (RMSE) on the already predicted ratings"""
        nOK = nKO = 0
            
        sumSqErr = 0
        sumAbsErr = 0

        for est, r0 in self.preds:
            sumSqErr += (r0 - est)**2
            sumAbsErr += abs(r0 - est)

            if est == r0:
                nOK += 1
            else:
                nKO += 1
        
        self.rmse = np.sqrt(sumSqErr / (nOK + nKO))
        self.mae = np.sqrt(sumAbsErr / (nOK + nKO))
        self.accRate = nOK / (nOK + nKO)

        if output:
            print('Nb impossible predictions:', self.nImp)
            print('RMSE:', self.rmse)
            print('MAE:', self.mae)
            print('Accuracy rate:', self.accRate)

class AlgoRandom(Algo):
    """predict a random rating based on the distribution of the training set"""
    
    def __init__(self, rm):
        super().__init__(rm)
        self.infos['name'] = 'random'

        # estimation of the distribution
        fqs = [0, 0, 0, 0, 0]
        for x in range(1, self.lastXi):
            for y in range(1, self.lastYi):
                if self.rm[x, y] > 0:
                    fqs[self.rm[x, y] - 1] += 1
        fqs = [fq/sum(fqs) for fq in fqs]
        self.distrib = rv_discrete(values=([1, 2, 3, 4, 5], fqs))

    def estimate(self, u0, m0):
        self.est = self.distrib.rvs()

class AlgoUsingCosineSim(Algo):
    """Abstract class for algos using cosine similarity"""
    def __init__(self, rm, movieBased=False):
        Algo.__init__(self,rm, movieBased)
        self.constructSimMat() # we'll need the similiarities

    def constructSimMat(self):
        """construct the simlarity matrix. measure = cosine sim"""
        # open or precalculate the similarity matrix if it does not exist yet
        try:
            print('Opening simFile')
            if self.ub:
                simFile = open('simCosUsers', 'rb')
                self.simMat = np.load(simFile)
            else:
                simFile = open('simCosMovies', 'rb')
                self.simMat = np.load(simFile)

        except IOError:
            print('Failed... Computation of similarities...')
            self.simMat = np.empty((self.lastXi + 1, self.lastXi + 1))
            for xi in range(1, self.lastXi + 1):
                for xj in range(1, self.lastXi + 1):
                    self.simMat[xi, xj] = self.simCos(xi, xj)
            if self.ub:
                simFile = open('simCosUsers', 'wb')
                np.save(simFile, self.simMat)
            else:
                simFile = open('simCosMovies', 'wb')
                np.save(simFile, self.simMat)

    def simCos(self, a, b):
        """ return the similarity between two users or movies using cosine
        distance"""
        # movies rated by a and b or users having rated a and b
        Yab = [y for y in range(1, self.lastYi + 1) if self.rm[a, y] > 0 and
            self.rm[b, y] > 0]

        # need to have at least two movies in common
        if len(Yab) < 2:
            return 0

        # list of ratings of/by a and b
        aR = [self.rm[a, y] for y in Yab]
        bR = [self.rm[b, y] for y in Yab]

        return 1 - cosine(aR, bR)

class AlgoBasicCollaborative(AlgoUsingCosineSim):
    """Basic collaborative filtering algorithm
    
    est = (weighted) average of ratings from the KNN
    Similarity = cosine similarity
    """

    def __init__(self, rm, movieBased=False):
        super().__init__(rm, movieBased)

        self.k = 40

        self.infos['name'] = 'basicCollaborative'
        self.infos['params']['similarity measure'] = 'cosine'
        self.infos['params']['k'] = self.k

    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)
        # list of (x, sim(x0, x)) for u having rated m0 or for m rated by x0
        simX0 = [(x, self.simMat[x0, x]) for x in range(1, self.lastXi + 1) if
            self.rm[x, y0] > 0]

        # if there is nobody on which predict the rating...
        if not simX0:
            self.est = 0
            return

        # sort simX0 by similarity
        simX0 = sorted(simX0, key=lambda x:x[1], reverse=True)

        # let the KNN vote
        simNeighboors = [sim for (_, sim) in simX0[:self.k]]
        ratNeighboors = [self.rm[x, y0] for (x, _) in simX0[:self.k]]
        try:
            self.est = int(round(np.average(ratNeighboors,
                weights=simNeighboors)))
        except ZeroDivisionError:
            self.est = 0

class AlgoUsingAnalogy(Algo):
    """Abstract class for algos that use an analogy framework"""
    def __init__(self, rm, ur, mr, movieBased=False):
        super().__init__(rm, ur, mr, movieBased)

    def isSolvable(self, ra, rb, rc):
        """return true if analogical equation is solvable else false"""
        return (ra == rb) or (ra == rc)

    def solve(self, ra, rb, rc):
        """ solve A*(a, b, c, x). Undefined if equation not solvable."""
        return rc - ra + rb

    def tvAStar (self, ra, rb, rc, rd):
        """return the truth value of A*(ra, rb, rc, rd)"""

        # map ratings into [0, 1]
        ra = (ra-1)/4.; rb = (rb-1)/4.; rc = (rc-1)/4.; rd = (rd-1)/4.; 
        return min(1 - abs(max(ra, rd) - max(rb, rc)), 1 - abs(min(ra, rd) -
            min(rb, rc)))

    def tvA(self, ra, rb, rc, rd):
        """return the truth value of A(ra, rb, rc, rd)"""

        # map ratings into [0, 1]
        ra = (ra-1)/4.; rb = (rb-1)/4.; rc = (rc-1)/4.; rd = (rd-1)/4.; 
        if (ra >= rb and rc >= rd) or (ra <= rb and rc <= rd):
            return 1 - abs((ra-rb) - (rc-rd))
        else:
            return 1 - max(abs(ra-rb), abs(rc-rd))
    
class AlgoAnalogy(AlgoUsingAnalogy):
    """analogy based recommender"""
    def __init__(self, rm, ur, mr, movieBased=False):
        super().__init__(rm, ur, mr, movieBased)
        self.infos['name'] = 'algoAnalogy'


    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)

        # if there are no ratings for y0, prediction is impossible
        if not self.yr[y0]:
            self.est = 0
            return

        sols = [] # solutions to analogical equation
        for i in range(1000):
            # randomly choose a, b, and c
            xa, ra = rd.choice(self.yr[y0])
            xb, rb = rd.choice(self.yr[y0])
            xc, rc = rd.choice(self.yr[y0])
            if xa != xb != xc and xa != xc and self.isSolvable(ra, rb, rc):
                tv = self.getTvVector(xa, xb, xc, x0)
                if tv:
                    sols.append((self.solve(ra, rb, rc), np.mean(tv)))

        ratings = [r for (r, _) in sols]
        weights = [w for (_, w) in sols]

        if not ratings or set(weights) == {0}:
            self.est = 0
            return
        self.est = int(round(np.average(ratings, weights=weights)))

    def getTvVector(self, xa, xb, xc, x0):
        tv = []

        # list of ys that xa, xb, xc, and x0 have commonly rated
        Yabc0 = [(self.rm[xa, y], self.rm[xb, y], self.rm[xc, y], self.rm[x0,
            y]) for (y, _) in self.xr[xa] if (self.rm[xb, y] and self.rm[xc, y]
            and self.rm[x0, y])]

        for ra, rb, rc, rd in Yabc0:
            #tv.append(self.tvAStar(ra, rb, rc, rd))
            tv.append(self.tvA(ra, rb, rc, rd))

        return tv



class AlgoGilles(AlgoUsingAnalogy):
    """geometrical analogy based recommender"""
    def __init__(self, rm, ur, mr, movieBased=False):
        super().__init__(rm, ur, mr, movieBased)
        self.infos['name'] = 'algoGilles'

    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)

        # if there are no ratings for y0, prediction is impossible
        if not self.yr[y0]:
            self.est = 0
            return

        candidates= [] # solutions to analogical equations
        for i in range(1000):
            # randomly choose a, b, and c
            xa, ra = rd.choice(self.yr[y0])
            xb, rb = rd.choice(self.yr[y0])
            xc, rc = rd.choice(self.yr[y0])
            if xa != xb != xc and xa != xc and self.isSolvable(ra, rb, rc):
                # get info about the abcd 'paralellogram'
                (nYabc0, nrm) = self.getParall(xa, xb, xc, x0)
                if nrm < 1.5 * np.sqrt(nYabc0): # we allow some margin
                    candidates.append((self.solve(ra, rb, rc), nrm,
                        nYabc0))

        # if there are candidates, estimate rating as a weighted average
        if candidates:
            ratings = [r for (r, _, _) in candidates]
            norms = [1/(nrm + 1) for (_, nrm, _) in candidates]
            nYs = [nY for (_, _, nY) in candidates]

            """
            self.est = int(round(np.average(ratings, weights=norms)))
            self.est = int(round(np.average(ratings, weights=nYs)))
            """
            self.est = int(round(np.average(ratings)))
        else:
            self.est = 0


    def getParall(self, xa, xb, xc, x0):
        """return information about the parallelogram formed by xs: number of
        ratings in common and norm of the differences (see formula)"""

        # list of ys that xa, xb, xc, and x0 have commonly rated
        Yabc0 = [y for (y, _) in self.xr[xa] if (self.rm[xb, y] and self.rm[xc, y]
            and self.rm[x0, y])]

        # if there is no common rating
        if not Yabc0:
            return 0, float('inf')

        # lists of ratings for common ys
        xaRs = np.array([self.rm[xa, y] for y in Yabc0])
        xbRs = np.array([self.rm[xb, y] for y in Yabc0])
        xcRs = np.array([self.rm[xc, y] for y in Yabc0])
        x0Rs = np.array([self.rm[x0, y] for y in Yabc0])

        # the closer the norm to zero, the more abcd is in a paralellogram
        # shape
        nrm = np.linalg.norm((xaRs - xbRs) - (xcRs - x0Rs))

        return len(Yabc0), nrm

class AlgoWithBaseline(Algo):
    """Abstract class for algos that need a baseline"""
    def __init__(self, rm, ur=None, mr=None, movieBased=False, method='opt'):
        Algo.__init__(self,rm, ur, mr, movieBased)

        #compute users and items biases
        # see from 5.2.1 of RS handbook

        # mean of all ratings from training set
        self.mu = np.mean([r for l in self.rm for r in l if r > 0])

        self.xBiases = np.zeros(self.lastXi + 1)
        self.yBiases = np.zeros(self.lastYi + 1)

        print('Estimating biases...')
        if method == 'opt':
            # using stochastic gradient descent optimisation
            lambda4 = 0.02
            gamma = 0.005
            nIter = 20
            for i in range(nIter):
                for x, xRatings in self.xr.items():
                    for y, r in xRatings:
                        err = r - (self.mu + self.xBiases[x] + self.yBiases[y])
                        # update xBiases 
                        self.xBiases[x] += gamma * (err - lambda4 *
                            self.xBiases[x])
                        # udapte yBiases
                        self.yBiases[y] += gamma * (err - lambda4 *
                            self.yBiases[y])
        else:
            # using a more basic method 
            if self.ub:
                lambda2 = 10.
                lambda3 = 25.
            else:
                lambda2 = 25.
                lambda3 = 10.

            for x in range(1, self.lastXi + 1):
                # list of deviations from average for x
                devX = [r - self.mu for (_, r) in self.xr[x]]
                self.xBiases[x] = sum(devX) / (lambda2 + len(devX))
            for y in range(1, self.lastYi + 1):
                # list of deviations from average for y
                devY = [r - self.mu for (_, r) in self.yr[y]]
                self.yBiases[y] = sum(devY) / (lambda3 + len(devY))


    def getBaseline(self, x, y):
        return self.mu + self.xBiases[x] + self.yBiases[y]


class AlgoBaselineOnly(AlgoWithBaseline):
    """ Algo using only baseline""" 

    def __init__(self, rm, ur, mr, movieBased=False, method='opt'):
        super().__init__(rm, ur, mr, movieBased, method)
        self.infos['name'] = 'algoBaselineOnly'

    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)
        self.est = self.getBaseline(x0, y0)

class AlgoNeighborhoodWithBaseline(AlgoWithBaseline, AlgoUsingCosineSim):
    """ Algo baseline AND deviation from baseline of the neighbors
        
        simlarity measure = cos"""
    def __init__(self, rm, ur, mr, movieBased=False, method='opt'):
        AlgoWithBaseline.__init__(self, rm, ur, mr, movieBased, method)
        AlgoUsingCosineSim.__init__(self, rm, movieBased)
        self.infos['name'] = 'neighborhoodWithBaseline'

    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)
        self.est = self.getBaseline(x0, y0)


        simX0 = [(x, self.simMat[x0, x], r) for (x, r) in self.yr[y0]]

        # if there is nobody on which predict the rating...
        if not simX0:
            return # result will be just the baseline

        # sort simX0 by similarity
        simX0 = sorted(simX0, key=lambda x:x[1], reverse=True)

        # let the KNN vote
        k = 40
        simNeighboors = [sim for (_, sim, _) in simX0[:k]]
        diffRatNeighboors = [r - self.getBaseline(x, y0) 
            for (x, _, r) in simX0[:k]]
        try:
            self.est += np.average(diffRatNeighboors, weights=simNeighboors)
        except ZeroDivisionError:
            return # just baseline

class AlgoKNNBelkor(AlgoWithBaseline):
    """ KNN learning interpolating weights from the training data. see 5.1.1
    from reco system handbook"""
    def __init__(self, rm, ur, mr, movieBased=False, method='opt'):
        super().__init__(rm, ur, mr, movieBased, method)
        self.weights = np.zeros((self.lastXi + 1, self.lastXi + 1),
        dtype='double')

        nIter = 20
        gamma = 0.005
        lambda10 = 0.002

        self.infos['name'] = 'KNNBellkor'

        for i in range(nIter):
            print("optimizing...", nIter - i, "iteration left")
            for x, xRatings in self.xr.items():
                for y, rxy in xRatings:
                    est = sum((r - self.getBaseline(x2, y)) *
                        self.weights[x, x2] for (x2, r) in self.yr[y])
                    est /= np.sqrt(len(self.yr[y]))
                    est += self.mu + self.xBiases[x] + self.yBiases[y]

                    err = rxy - est

                    # update x bias
                    self.xBiases[x] += gamma * (err - lambda10 *
                        self.xBiases[x])

                    # update y bias
                    self.yBiases[y] += gamma * (err - lambda10 *
                        self.yBiases[y])

                    # update weights
                    for x2, rx2y in self.yr[y]:
                        bx2y = self.getBaseline(x2, y)
                        wxx2 = self.weights[x, x2]
                        self.weights[x, x2] += gamma * ((err * (rx2y -
                            bx2y)/np.sqrt(len(self.yr[y]))) - (lambda10 * wxx2))


    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)
        
        self.est = sum((r - self.getBaseline(x2, y0)) *
            self.weights[x0, x2] for (x2, r) in self.yr[y0])
        self.est /= np.sqrt(len(self.yr[y0]))
        self.est += self.getBaseline(x0, y0)

        self.est = min(5, self.est)
        self.est = max(1, self.est)

