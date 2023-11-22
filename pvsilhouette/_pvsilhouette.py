# -*- coding: utf-8 -*-
#----------------------------------------------------------------------------
# Created By  : Yusuke Aso
# Created Date: 2022 Jan 27
# Updated Date: 2023 Nov 21 by J.Sai
# version = alpha
# ---------------------------------------------------------------------------
"""
This script makes position-velocity diagrams along the major anc minor axes and reproduces their silhouette by the UCM envelope.
The main class PVSilhouette can be imported to do each steps separately.

Note. FITS files with multiple beams are not supported. The dynamic range for xlim_plot and vlim_plot should be >10 for nice tick labels.
"""

import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits
from astropy import constants
from astropy.coordinates import SkyCoord
from scipy.interpolate import RegularGridInterpolator as RGI
from tqdm import tqdm
import warnings

from utils import emcee_corner
from pvsilhouette.ulrichenvelope import velmax, mockpvd

warnings.simplefilter('ignore', RuntimeWarning)


class PVSilhouette():

#    def __init__(self):

    def read_cubefits(self, cubefits: str, center: str = None,
                      dist: float = 1, vsys: float = 0,
                      xmax: float = 1e4, ymax: float = 1e4,
                      vmin: float = -100, vmax: float = 100,
                      sigma: float = None) -> dict:
        """
        Read a position-velocity diagram in the FITS format.

        Parameters
        ----------
        cubefits : str
            Name of the input FITS file including the extension.
        center : str
            Coordinates of the target: e.g., "01h23m45.6s 01d23m45.6s".
        dist : float
            Distance of the target, used to convert arcsec to au.
        vsys : float
            Systemic velocity of the target.
        xmax : float
            The R.A. axis is limited to (-xmax, xmax) in the unit of au.
        ymax : float
            The Dec. axis is limited to (-xmax, xmax) in the unit of au.
        vmax : float
            The velocity axis of the PV diagram is limited to (vmin, vmax).
        vmin : float
            The velocity axis of the PV diagram is limited to (vmin, vmax).
        sigma : float
            Standard deviation of the FITS data. None means automatic.

        Returns
        ----------
        fitsdata : dict
            x (1D array), v (1D array), data (2D array), header, and sigma.
        """
        cc = constants.c.si.value
        f = fits.open(cubefits)[0]
        d, h = np.squeeze(f.data), f.header
        if center is None:
            cx, cy = 0, 0
        else:
            coord = SkyCoord(center, frame='icrs')
            cx = coord.ra.degree - h['CRVAL1']
            cy = coord.dec.degree - h['CRVAL2']
        if sigma is None:
            sigma = np.mean([np.nanstd(d[:2]), np.std(d[-2:])])
            print(f'sigma = {sigma:.3e}')
        x = (np.arange(h['NAXIS1']) - h['CRPIX1'] + 1) * h['CDELT1']
        y = (np.arange(h['NAXIS2']) - h['CRPIX2'] + 1) * h['CDELT2']
        v = (np.arange(h['NAXIS3']) - h['CRPIX3'] + 1) * h['CDELT3']
        v = v + h['CRVAL3']
        x = (x - cx) * 3600. * dist  # au
        y = (y - cy) * 3600. * dist  # au
        v = (1. - v / h['RESTFRQ']) * cc / 1.e3 - vsys  # km/s
        i0, i1 = np.argmin(np.abs(x - xmax)), np.argmin(np.abs(x + xmax))
        j0, j1 = np.argmin(np.abs(y + ymax)), np.argmin(np.abs(y - ymax))
        k0, k1 = np.argmin(np.abs(v - vmin)), np.argmin(np.abs(v - vmax))
        self.offpix = (i0, j0, k0)
        x, y, v = x[i0:i1 + 1], y[j0:j1 + 1], v[k0:k1 + 1],
        d =  d[k0:k1 + 1, j0:j1 + 1, i0:i1 + 1]
        dx, dy, dv = x[1] - x[0], y[1] - y[0], v[1] - v[0]
        if 'BMAJ' in h.keys():
            bmaj = h['BMAJ'] * 3600. * dist  # au
            bmin = h['BMIN'] * 3600. * dist  # au
            bpa = h['BPA']  # deg
        else:
            bmaj, bmin, bpa = dy, -dx, 0
            print('No valid beam in the FITS file.')
        self.x, self.dx = x, dx
        self.y, self.dy = y, dy
        self.v, self.dv = v, dv
        self.data, self.header, self.sigma = d, h, sigma
        self.bmaj, self.bmin, self.bpa = bmaj, bmin, bpa
        self.cubefits, self.dist, self.vsys = cubefits, dist, vsys
        return {'x':x, 'y':y, 'v':v, 'data':d, 'header':h, 'sigma':sigma}

    def read_pvfits(self, pvfits: str,
                    dist: float = 1, vsys: float = 0,
                    xmax: float = 1e4,
                    vmin: float = -100, vmax: float = 100,
                    sigma: float = None) -> dict:
        """
        Read a position-velocity diagram in the FITS format.

        Parameters
        ----------
        pvfits : str
            Name of the input FITS file including the extension.
        dist : float
            Distance of the target, used to convert arcsec to au.
        vsys : float
            Systemic velocity of the target.
        xmax : float
            The positional axis is limited to (-xmax, xmax) in the unit of au.
        vmin : float
            The velocity axis is limited to (-vmax, vmax) in the unit of km/s.
        vmax : float
            The velocity axis is limited to (-vmax, vmax) in the unit of km/s.
        sigma : float
            Standard deviation of the FITS data. None means automatic.

        Returns
        ----------
        fitsdata : dict
            x (1D array), v (1D array), data (2D array), header, and sigma.
        """
        cc = constants.c.si.value
        f = fits.open(pvfits)[0]
        d, h = np.squeeze(f.data), f.header
        if sigma is None:
            sigma = np.mean([np.std(d[:2, 10:-10]), np.std(d[-2:, 10:-10]),
                             np.std(d[2:-2, :10]), np.std(d[2:-2, -10:])])
            print(f'sigma = {sigma:.3e}')
        x = (np.arange(h['NAXIS1'])-h['CRPIX1']+1)*h['CDELT1']+h['CRVAL1']
        v = (np.arange(h['NAXIS2'])-h['CRPIX2']+1)*h['CDELT2']+h['CRVAL2']
        x = x * dist  # au
        v = (1. - v / h['RESTFRQ']) * cc / 1.e3 - vsys  # km/s
        i0, i1 = np.argmin(np.abs(x + xmax)), np.argmin(np.abs(x - xmax))
        j0, j1 = np.argmin(np.abs(v - vmin)), np.argmin(np.abs(v - vmax))
        x, v, d = x[i0:i1 + 1], v[j0:j1 + 1], d[j0:j1 + 1, i0:i1 + 1]
        dx, dv = x[1] - x[0], v[1] - v[0]
        if 'BMAJ' in h.keys():
            dNyquist = (bmaj := h['BMAJ'] * 3600. * dist) / 2.  # au
            self.beam = [h['BMAJ'] * 3600. * dist, h['BMIN'] * 3600. * dist, h['BPA']]
        else:
            dNyquist = bmaj = np.abs(dx)  # au
            self.beam = None
            print('No valid beam in the FITS file.')
        self.x, self.dx = x, dx
        self.v, self.dv = v, dv
        self.data, self.header, self.sigma = d, h, sigma
        self.bmaj, self.dNyquist = bmaj, dNyquist
        self.pvfits, self.dist, self.vsys = pvfits, dist, vsys
        return {'x':x, 'v':v, 'data':d, 'header':h, 'sigma':sigma}

    def get_PV(self, cubefits: str = None,
               pa: float = 0, center: str = None,
               dist: float = 1, vsys: float = 0,
               xmax: float = 1e4,
               vmin: float = -100, vmax: float = 100,
               sigma: float = None):
        if not (cubefits is None):
            self.read_cubefits(cubefits, center, dist, vsys,
                               xmax, xmax, vmin, vmax, sigma)
        x, y, v = self.x, self.y, self.v
        sigma, d = self.sigma, self.data
        n = np.floor(xmax / self.dy)
        r = (np.arange(2 * n + 1) - n) * self.dy
        ry = r * np.cos(np.radians(pa))
        rx = r * np.sin(np.radians(pa))
        dpvmajor = [None] * len(v)
        dpvminor = [None] * len(v)
        for i in range(len(v)):
            interp = RGI((-x, y), d[i], bounds_error=False)
            dpvmajor[i] = interp((-rx, ry))
            dpvminor[i] = interp((ry, rx))
        self.dpvmajor = np.array(dpvmajor)
        self.dpvminor = np.array(dpvminor)
        self.x = r
    
    def put_PV(self, pvmajorfits: str, pvminorfits: str,
               dist: float, vsys: float,
               rmax: float, vmin: float, vmax: float, sigma: float):
        self.read_pvfits(pvmajorfits, dist, vsys, rmax, vmin, vmax, sigma)
        self.dpvmajor = self.data
        self.read_pvfits(pvminorfits, dist, vsys, rmax, vmin, vmax, sigma)
        self.dpvminor = self.data

    def fitting(self, incl: float = 90,
                Mstar_range: list = [0.01, 10],
                Rc_range: list = [1, 1000],
                alphainfall_range: list = [0.01, 1],
                Mstar_fixed: float = None,
                Rc_fixed: float = None,
                alphainfall_fixed: float = None,
                cutoff: float = 5, vmask: list = [0, 0],
                figname: str = 'PVsilhouette',
                show: bool = False,
                progressbar: bool = True,
                kwargs_emcee_corner: dict = {}):
        majobs = np.where(self.dpvmajor > cutoff * self.sigma, 1, 0)
        minobs = np.where(self.dpvminor > cutoff * self.sigma, 1, 0)
        x, v = np.meshgrid(self.x, self.v)
        def minmax(a: np.ndarray, b: np.ndarray, s: str, m: np.ndarray):
            rng = a[(b >= 0 if s == '+' else b < 0) * (m > 0.5)]
            if len(rng) == 0:
                return 0, 0
            else:
                return np.min(rng), np.max(rng)
        rng = np.array([[[minmax(a, b, s, m)
                          for m in [majobs, minobs]]
                         for s in ['-', '+']]
                        for a, b in zip([x, v], [v, x])])
        def combine(r: np.ndarray):
            return np.min(r[:, 0]), np.max(r[:, 1])
        rng = [[combine(r) for r in rr] for rr in rng]
        mask = [[(s * a > 0) * ((b < r[0]) + (r[1] < b))
                 for s, r in zip([-1, 1], rr)]
                for a, b, rr in zip([v, x], [x, v], rng)]
        mask = np.sum(mask, axis=(0, 1)) + (vmask[0] < v) * (v < vmask[1])
        majobs = np.where(mask, np.nan, majobs)
        minobs = np.where(mask, np.nan, minobs)
        majsig = 1
        minsig = 1
        def calcchi2(majmod: np.ndarray, minmod: np.ndarray):
            chi2 =   np.nansum((majobs - majmod)**2 / majsig**2) \
                   + np.nansum((minobs - minmod)**2 / minsig**2)
            return chi2
        
        chi2max1 = calcchi2(np.ones_like(majobs), np.ones_like(minobs))
        chi2max0 = calcchi2(np.zeros_like(majobs), np.zeros_like(minobs))
        chi2max = np.min([chi2max0, chi2max1])
        def getquad(m):
            nv, nx = np.shape(m)
            q =   np.sum(m[:nv//2, :nx//2]) + np.sum(m[nv//2:, nx//2:]) \
                - np.sum(m[nv//2:, :nx//2]) - np.sum(m[:nv//2, nx//2:])
            return int(np.sign(q))
        majquad = getquad(self.dpvmajor)
        minquad = getquad(self.dpvminor) * (-1)
        def makemodel(Mstar, Rc, alphainfall, outputvel=False):
            a = velmax(self.x, Mstar=Mstar, Rc=Rc,
                       alphainfall=alphainfall, incl=incl)
            major = []
            for min, max in zip(a['major']['vlosmin'], a['major']['vlosmax']):
                major.append(np.where((min < self.v) * (self.v < max), 1, 0))
            major = np.transpose(major)[:, ::majquad]
            minor = []
            for min, max in zip(a['minor']['vlosmin'], a['minor']['vlosmax']):
                minor.append(np.where((min < self.v) * (self.v < max), 1, 0))
            minor = np.transpose(minor)[:, ::minquad]
            if outputvel:
                return major, minor, a
            else:
                return major, minor
        p_fixed = np.array([Mstar_fixed, Rc_fixed, alphainfall_fixed])
        if None in p_fixed:
            labels = np.array(['log Mstar', 'log Rc', r'log $\alpha$'])
            labels = labels[p_fixed == None]
            kwargs0 = {'nwalkers_per_ndim':16, 'nburnin':100, 'nsteps':500,
                       'rangelevel':None, 'labels':labels,
                       'figname':figname+'.corner.png', 'show_corner':show}
            kwargs = dict(kwargs0, **kwargs_emcee_corner)
            if progressbar:
                total = kwargs['nwalkers_per_ndim'] * len(p_fixed[p_fixed == None])
                total *= kwargs['nburnin'] + kwargs['nsteps'] + 2
                bar = tqdm(total=total)
                bar.set_description('Within the ranges')
            def lnprob(p):
                if progressbar:
                    bar.update(1)
                q = p_fixed.copy()
                q[p_fixed == None] = 10**p
                chi2 = calcchi2(*makemodel(*q))
                return -np.inf if chi2 > chi2max else -0.5 * chi2
            plim = np.array([Mstar_range, Rc_range, alphainfall_range])
            plim = np.log10(plim[p_fixed == None]).T
            mcmc = emcee_corner(plim, lnprob, simpleoutput=False, **kwargs)
            if np.isinf(lnprob(mcmc[0])):
                print('No model is better than the all-0 or all-1 models.')
            popt = p_fixed.copy()
            popt[p_fixed == None] = 10**mcmc[0]
            plow = p_fixed.copy()
            plow[p_fixed == None] = 10**mcmc[1]
            phigh = p_fixed.copy()
            phigh[p_fixed == None] = 10**mcmc[3]
        else:
            popt = p_fixed
            plow = p_fixed
            phigh = p_fixed
        self.popt = popt
        self.plow = plow
        self.phigh = phigh
        print(f'M* = {plow[0]:.2f}, {popt[0]:.2f}, {phigh[0]:.2f} Msun')
        print(f'Rc = {plow[1]:.0f}, {popt[1]:.0f}, {phigh[1]:.0f} au')
        print(f'alpha = {plow[2]:.2f}, {popt[2]:.2f}, {phigh[2]:.2f}')

        majmod, minmod, a = makemodel(*popt, outputvel=True)
        fig = plt.figure()
        ax = fig.add_subplot(1, 2, 1)
        z = np.where(mask, -(mask.astype('int')), (majobs - majmod)**2)
        ax.pcolormesh(self.x, self.v, z, cmap='bwr', vmin=-1, vmax=1, alpha=0.1)
        ax.contour(self.x, self.v, self.dpvmajor,
                   levels=np.arange(1, 10) * 3 * self.sigma, colors='k')
        ax.plot(self.x * majquad, a['major']['vlosmax'], '-r')
        ax.plot(self.x * majquad, a['major']['vlosmin'], '-r')
        ax.set_xlabel('major offset (au)')
        ax.set_ylabel(r'$V-V_{\rm sys}$ (km s$^{-1}$)')
        ax.set_ylim(np.min(self.v), np.max(self.v))
        ax = fig.add_subplot(1, 2, 2)
        z = np.where(mask, -(mask.astype('int')), (minobs - minmod)**2)
        ax.pcolormesh(self.x, self.v, z, cmap='bwr', vmin=-1, vmax=1, alpha=0.1)
        ax.contour(self.x, self.v, self.dpvminor,
                   levels=np.arange(1, 10) * 3 * self.sigma, colors='k')
        ax.plot(self.x * minquad, a['minor']['vlosmax'], '-r')
        ax.plot(self.x * minquad, a['minor']['vlosmin'], '-r')
        ax.set_xlabel('minor offset (au)')
        ax.set_ylim(self.v.min(), self.v.max())
        ax.set_title(r'$M_{*}$'+f'={popt[0]:.2f}'+r'$M_{\odot}$'
            +', '+r'$R_{c}$'+f'={popt[1]:.0f} au'
            +'\n'+r'$\alpha$'+f'={popt[2]:.2f}'
            +', '+r'$\alpha ^{2} M_{*}$'+f'={popt[0] * popt[2]**2:.2}')
        fig.tight_layout()
        fig.savefig(figname + '.model.png')
        if show: plt.show()


    def fit_mockpvd(self, 
                incl: float = 89.,
                Mstar_range: list = [0.01, 10],
                Rc_range: list = [1, 1000],
                alphainfall_range: list = [0.01, 1],
                fscale_range: list = [0.01, 100.],
                Mstar_fixed: float = None,
                Rc_fixed: float = None,
                alphainfall_fixed: float = None,
                fscale_fixed: float = None,
                cutoff: float = 5, 
                vmask: list = [0, 0],
                figname: str = 'PVsilhouette',
                show: bool = False,
                progressbar: bool = True,
                kwargs_emcee_corner: dict = {},
                pa_maj = None,
                beam = None, p0 = None):
        # Observed pv diagrams
        majobs = self.dpvmajor.copy()
        minobs = self.dpvminor.copy()
        #majobs[majobs < cutoff * self.sigma] = np.nan
        #minobs[minobs < cutoff * self.sigma] = np.nan
        x, v = np.meshgrid(self.x, self.v)
        def minmax(a: np.ndarray, b: np.ndarray, s: str, m: np.ndarray):
            rng = a[(b >= 0 if s == '+' else b < 0) * (m > 0.5)]
            if len(rng) == 0:
                return 0, 0
            else:
                return np.min(rng), np.max(rng)
        rng = np.array([[[minmax(a, b, s, m)
                          for m in [majobs, minobs]]
                         for s in ['-', '+']]
                        for a, b in zip([x, v], [v, x])])
        def combine(r: np.ndarray):
            return np.min(r[:, 0]), np.max(r[:, 1])
        rng = [[combine(r) for r in rr] for rr in rng]
        mask = [[(s * a > 0) * ((b < r[0]) + (r[1] < b))
                 for s, r in zip([-1, 1], rr)]
                for a, b, rr in zip([v, x], [x, v], rng)]
        mask = np.sum(mask, axis=(0, 1)) + (vmask[0] < v) * (v < vmask[1])
        majobs = np.where(mask, np.nan, majobs)
        minobs = np.where(mask, np.nan, minobs)
        majsig, minsig = self.sigma, self.sigma
        def calcchi2(majmod: np.ndarray, minmod: np.ndarray):
            chi2 =   np.nansum((majobs - majmod)**2 / majsig**2) \
                   + np.nansum((minobs - minmod)**2 / minsig**2)
            return chi2
        
        chi2max1 = calcchi2(majobs, minobs)
        chi2max0 = calcchi2(majobs, minobs)
        chi2max = np.min([chi2max0, chi2max1])
        def getquad(m):
            nv, nx = np.shape(m)
            q =   np.sum(m[:nv//2, :nx//2]) + np.sum(m[nv//2:, nx//2:]) \
                - np.sum(m[nv//2:, :nx//2]) - np.sum(m[:nv//2, nx//2:])
            return int(np.sign(q))
        majquad = getquad(self.dpvmajor)
        minquad = getquad(self.dpvminor) * (-1)

        obsmax = max(np.nanmax(majobs), np.nanmax(minobs))
        def makemodel(Mstar, Rc, alphainfall, fscale):
            major = mockpvd(self.x, self.x, self.v, Mstar, Rc,
                alphainfall=alphainfall, incl=incl, axis='major',
                fscale = obsmax, beam = self.beam, pa=pa_maj, rout=np.nanmax(self.x))
            major = major[:, ::majquad] * fscale
            minor = mockpvd(self.x, self.x, self.v, Mstar, Rc,
                alphainfall=alphainfall, incl=incl, axis='minor',
                fscale = obsmax, beam = self.beam, pa=pa_maj - 90., rout=np.nanmax(self.x))
            minor = minor[:, ::minquad] * fscale
            return major, minor


        # chi2 fitting
        #from scipy.optimize import least_squares
        #f_lsfit = lambda params: calcchi2(*makemodel(*params))
        #plim = np.array([Mstar_range, Rc_range, alphainfall_range, fscale_range])
        #print('Run fitting..')
        #res = least_squares(f_lsfit, p0, bounds=plim.T)
        #popt = res.x #[ x for x in res.x]
        #print('Done.')
        #print(popt)
        #return popt


        # Fitting
        p_fixed = np.array([Mstar_fixed, Rc_fixed, alphainfall_fixed, fscale_fixed])
        if None in p_fixed:
            labels = np.array(['log Mstar', 'log Rc', r'log $\alpha$', r'log f'])
            labels = labels[p_fixed == None]
            kwargs0 = {'nwalkers_per_ndim':2, 'nburnin':250, 'nsteps':250, # 16, 100, 500
                       'rangelevel':None, 'labels':labels,
                       'figname':figname+'.corner.png', 'show_corner':show}
            kwargs = dict(kwargs0, **kwargs_emcee_corner)
            if progressbar:
                total = kwargs['nwalkers_per_ndim'] * len(p_fixed[p_fixed == None])
                total *= kwargs['nburnin'] + kwargs['nsteps'] + 2
                bar = tqdm(total=total)
                bar.set_description('Within the ranges')
            def lnprob(p):
                if progressbar:
                    bar.update(1)
                q = p_fixed.copy()
                q[p_fixed == None] = 10**p
                chi2 = calcchi2(*makemodel(*q))
                return -0.5 * chi2 # -np.inf if chi2 > chi2max else
            plim = np.array([Mstar_range, Rc_range, alphainfall_range, fscale_range])
            plim = np.log10(plim[p_fixed == None]).T
            mcmc = emcee_corner(plim, lnprob, simpleoutput=False, **kwargs)
            if np.isinf(lnprob(mcmc[0])):
                print('No model is better than the all-0 or all-1 models.')
            popt = p_fixed.copy()
            popt[p_fixed == None] = 10**mcmc[0]
            plow = p_fixed.copy()
            plow[p_fixed == None] = 10**mcmc[1]
            phigh = p_fixed.copy()
            phigh[p_fixed == None] = 10**mcmc[3]
        else:
            popt = p_fixed
            plow = p_fixed
            phigh = p_fixed
        self.popt = popt
        self.plow = plow
        self.phigh = phigh
        print(f'M* = {plow[0]:.2f}, {popt[0]:.2f}, {phigh[0]:.2f} Msun')
        print(f'Rc = {plow[1]:.0f}, {popt[1]:.0f}, {phigh[1]:.0f} au')
        print(f'alpha = {plow[2]:.2f}, {popt[2]:.2f}, {phigh[2]:.2f}')
        print(f'f = {plow[3]:.2f}, {popt[3]:.2f}, {phigh[3]:.2f}')


        # plot
        majmod, minmod = makemodel(*popt, outputvel=True)
        fig = plt.figure()
        ax = fig.add_subplot(1, 2, 1)
        z = np.where(mask, -(mask.astype('int')), (majobs - majmod)**2)
        ax.pcolormesh(self.x, self.v, z, cmap='bwr', vmin=-1, vmax=1, alpha=0.1)
        ax.contour(self.x, self.v, self.dpvmajor,
                   levels=np.arange(1, 10) * 3 * self.sigma, colors='k')
        ax.plot(self.x * majquad, a['major']['vlosmax'], '-r')
        ax.plot(self.x * majquad, a['major']['vlosmin'], '-r')
        ax.set_xlabel('major offset (au)')
        ax.set_ylabel(r'$V-V_{\rm sys}$ (km s$^{-1}$)')
        ax.set_ylim(np.min(self.v), np.max(self.v))
        ax = fig.add_subplot(1, 2, 2)
        z = np.where(mask, -(mask.astype('int')), (minobs - minmod)**2)
        ax.pcolormesh(self.x, self.v, z, cmap='bwr', vmin=-1, vmax=1, alpha=0.1)
        ax.contour(self.x, self.v, self.dpvminor,
                   levels=np.arange(1, 10) * 3 * self.sigma, colors='k')
        ax.plot(self.x * minquad, a['minor']['vlosmax'], '-r')
        ax.plot(self.x * minquad, a['minor']['vlosmin'], '-r')
        ax.set_xlabel('minor offset (au)')
        ax.set_ylim(self.v.min(), self.v.max())
        ax.set_title(r'$M_{*}$'+f'={popt[0]:.2f}'+r'$M_{\odot}$'
            +', '+r'$R_{c}$'+f'={popt[1]:.0f} au'
            +'\n'+r'$\alpha$'+f'={popt[2]:.2f}'
            +', '+r'$\alpha ^{2} M_{*}$'+f'={popt[0] * popt[2]**2:.2}')
        fig.tight_layout()
        fig.savefig(figname + '.model.png')
        if show: plt.show()