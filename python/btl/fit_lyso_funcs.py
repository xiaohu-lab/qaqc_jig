from __future__ import division
import numpy as np
from scipy.stats import norm
import ROOT
from functools import cache

# Single photoelectron charge in attenuated mode
SPE_CHARGE = 1.0 # pC
# Single photoelectron charge standard deviation in attenuated mode
# FIXME: Should actually measure this
SPE_ERROR = 0.01 # pC

def dn(E,Q,Z,A,forb=None):
    """
    This function, dn(E,Q,Z,forb) Calculates the branch antineutrino kinetic
    energy spectrum. It takes the following variables: Q, the branch endpoint;
    Z, the number of protons in the daughter nucleus; forb, the forbiddenness.
    E the energy of the neutrino.

    From https://github.com/gzangakis/beta-spectrum/blob/master/BetaDecay.py
    """

    e = E

    if not 0 < E <= Q:
        return 0

    # Fermi Function approximation
    if e < 613.2:
        a = - 0.811 + (4.46e-2 * Z) + (1.08e-4 * (Z**2))
        b = 0.673 - (1.82e-2 * Z) + (6.38e-5 * (Z**2))

    if e >= 613.2:
        a = - 8.46e-2 + (2.48e-2 * Z) + (2.37e-4*(Z**2))
        b = 1.15e-2 + (3.58e-4 * Z) - (6.17e-5*(Z**2))

    P = np.sqrt(np.power(e+511,2)-np.power(511,2))
    F = ((e+511)/P) * np.exp( a + (b * np.sqrt(((e+511)/511)-1)))
    # Define Forbiddenness correction
    if forb=='1U':
        forbiddenness = P**2+(Q-e)**2
    elif forb=='2U':
        forbiddenness=(Q-e)**4+(10/3)*P**2*(Q-e)**2+P**2
    elif forb=='3U':
        forbiddenness=(Q-e)**6+7*P**2*(Q-e)**4+7*P**4*(Q-e)**2+P**6
    else: 
        forbiddenness=1

    # Branch Spectrum
    return forbiddenness*F*(np.sqrt(np.power(e,2)+2*e*511)*np.power(Q-e,2)*(e+511))

# Photons per keV
LIGHT_YIELD = 1500/1000.0

CACHE = {}

EPSILON = 1e-10

@cache
def p_e(es, p):
    Z = 72
    Q = 593
    A = 176 #Not sure if this is right?

    spectrum_88 = np.array([dn(e-88, Q, Z, A) for e in es],dtype=float)
    spectrum_290 = np.array([dn(e-290, Q, Z, A) for e in es],dtype=float)
    spectrum_395 = np.array([dn(e-395, Q, Z, A) for e in es],dtype=float)
    spectrum_597 = np.array([dn(e-597, Q, Z, A) for e in es],dtype=float)

    spectrum_88 += EPSILON
    spectrum_290 += EPSILON
    spectrum_395 += EPSILON
    spectrum_597 += EPSILON

    spectrum_88 /= np.trapz(spectrum_88,x=es)
    spectrum_290 /= np.trapz(spectrum_290,x=es)
    spectrum_395 /= np.trapz(spectrum_395,x=es)
    spectrum_597 /= np.trapz(spectrum_597,x=es)

    total_spectrum = p[0]*spectrum_88 + p[1]*spectrum_290 + p[2]*spectrum_395 + p[3]*spectrum_597

    return total_spectrum

def fast_norm(x,mu,sigma):
    return np.exp(-(x-mu)**2/(2*sigma**2))/(np.sqrt(2*np.pi)*sigma)

def p_q(q, y, e):
    n = y*e/SPE_CHARGE
    return fast_norm(q,y*e,np.sqrt(n)*SPE_CHARGE)

def likelihood(q,avg_y,dy,p):
    """
    Returns P(q|avg_y,dy,p) where avg_y is the average light yield, dy is the
    fractional difference between the light yield at the center and end of the
    bar, and p is a tuple containing the coefficients for the different gamma
    captures.

    A simple derivation of the likelihood is:

        p(q) = int_e p(q|e) p(e)
        p(q) = int_e int_y p(q|e,y) p(y) p(e)
        p(q) = int_e int_y p(q|e,y) p(e) # Assume p(y) = constant
        p(q) = int_e int_y Gauss(q,e*y,sqrt(e*y/SPE_CHARGE)*SPE_CHARGE) p(e)

    See the document "Fitting LYSO Intrinsic Spectrum" for more details.
    """

    ys = avg_y*np.linspace(1-dy,1+dy,10)[:,np.newaxis]
    es = np.linspace(1,1000,1000)

    # Here, we assume p(y) = constant
    return np.trapz(p_e(tuple(es),tuple(p))*np.trapz(p_q(q,ys,es)/(2*dy),x=ys,axis=0),x=es,axis=0)

def lyso_spectrum(x,p):
    """
    ROOT function to return the LYSO spectrum at x[0] in keV.

    p[0] - Average Light yield (pC/keV)
    p[1] - Fractional difference between light yield at center and side
    p[2] - Constant for 88 keV spectrum
    p[3] - Constant for 290 keV spectrum
    p[4] - Constant for 395 keV spectrum
    p[5] - Constant for 597 keV spectrum
    """
    qs = np.linspace(88,500,1000)

    key = tuple(p[i] for i in range(6))
    if key in CACHE:
        total_spectrum = CACHE[key]
        return np.interp(x[0],qs,total_spectrum)

    ps = [p[i] for i in range(2,6)]

    total_spectrum = [likelihood(q,p[0],p[1],ps) for q in qs]

    CACHE[key] = total_spectrum

    return np.interp(x[0],qs,total_spectrum)

def get_lyso(x, p):
    f = ROOT.TF1("flyso",lyso_spectrum,0,1000,6)
    for i in range(6):
        f.SetParameter(i,p[i])
    return np.array([f.Eval(e) for e in x])

def fit_lyso(h):
    """
    Fit the internal LYSO radiation spectrum to the histogram `h`. LYSO has
    intrinsic radiation from the beta decay of 176Lu (see
    https://www.nature.com/articles/s41598-018-35684-x). Here we fit the
    histogram to a sum of beta decay spectrums offset by 88, 202+88, 307+88,
    etc. where the offsets come from the gammas emitted when the daughter
    nucleus 176Hf relaxes.

    If the fit is successful, returns a list of the fit parameters:
        p[0] - Average light yield (pC/keV)
        p[1] - Fractional difference between light yield at center and side
        p[2] - Constant for 88 keV spectrum
        p[3] - Constant for 290 keV spectrum
        p[4] - Constant for 395 keV spectrum
        p[5] - Constant for 597 keV spectrum

    Otherwise, returns None.
    """
    f = ROOT.TF1("flyso",lyso_spectrum,0,1000,6)
    xmax = None
    ymax = 0
    for i in range(1,h.GetNbinsX()-1):
        x = h.GetBinCenter(i)
        value = h.GetBinContent(i)
        if x > 100 and value > ymax:
            xmax = x
            ymax = value

    if xmax is None:
        return None

    # Assume peak is somewhere around 300 keV
    f.SetParameter(0,xmax/300)
    f.SetParLimits(0,0.1,10)
    f.SetParameter(1,0.1)
    f.SetParLimits(1,0.01,0.2)
    f.SetParameter(2,h.GetEntries())
    f.SetParLimits(2,0,1e9)
    f.SetParameter(3,h.GetEntries())
    f.SetParLimits(3,0,1e9)
    f.SetParameter(4,0)
    f.SetParLimits(4,0,1e9)
    f.SetParameter(5,0)
    f.SetParLimits(5,0,1e9)

    # Right now we don't fit for these higher energy components. In the future
    # if we decrease the negative voltage rail we might be able to see these
    # without the waveform getting saturated at the negative rail.
    f.FixParameter(4,0)
    f.FixParameter(5,0)

    # Run the first fit only floating the normalization constants
    f.FixParameter(0,xmax/300)
    f.FixParameter(1,0.1)
    fr = h.Fit(f,"S+","",xmax-100,xmax+100)

    # Now we float all the parameters
    f.ReleaseParameter(0)
    f.ReleaseParameter(1)
    f.SetParLimits(0,0.1,10)
    f.SetParLimits(1,0.01,0.2)
    fr = h.Fit(f,"S+","",xmax-100,xmax+100)
    if not fr.Get().IsValid():
        return None
    return [f.GetParameter(i) for i in range(6)], [f.GetParError(i) for i in range(6)]

if __name__ == '__main__':
    import matplotlib.pyplot as plt

    x = np.linspace(0,500,500)
    f = ROOT.TF1("flyso",lyso_spectrum,0,1000,6)
    f.SetParameter(0,1)
    f.SetParameter(1,0.001)
    f.SetParameter(2,1)
    f.SetParameter(3,1)
    f.SetParameter(4,0)
    f.SetParameter(5,0)
    y = [f.Eval(e) for e in x]
    f.SetParameter(1,0.1)
    y2 = [f.Eval(e) for e in x]

    plt.plot(x,y,label='dy=0.001')
    plt.plot(x,y2,label='dy=0.1')
    plt.legend()
    plt.show()
