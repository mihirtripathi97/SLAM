import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits
from astropy import constants, units



# Constants (in cgs)
Ggrav  = constants.G.cgs.value     # Gravitational constant
Msun   = constants.M_sun.cgs.value # Solar mass (g)
au     = units.au.to('cm')         # au (cm)
clight = constants.c.cgs.value     # light speed (cm s^-1)


class Impvfits:
    '''
    Read a fits file of a position-velocity (PV) diagram.


    Variables
    ---------
    self.file: fits file name
    self.data (array): data
    self.header: Header info.
    '''

    def __init__(self, infile, pa=None, multibeam=False):
        self.file = infile
        with fits.open(infile) as hdul:
            # get primary
            self.data   = hdul[0].data
            self.header = hdul[0].header
            # multibeam?
            if 'CASAMBM' in self.header:
                multibeam = self.header['CASAMBM']
            self.multibeam = multibeam
            if multibeam:
                try:
                    self.multibeamtable = hdul['BEAMS'].copy()
                except KeyError as e:
                    self.multibeamtable = None
                    print('KeyError: '+e)
                    print('Could not find a multibeam table.')
            else:
                self.multibeamtable = None


        self.read_pvfits(pa=pa, multibeam=multibeam)
        #self.results = []


    # Read fits file of Poistion-velocity (PV) diagram
    def read_pvfits(self, pa=None, multibeam=False):
        '''
        Read fits file of pv diagram. P.A. angle of PV cut cab be given as an option.
        '''
        # read header
        header = self.header
        # number of axis
        naxis = header['NAXIS']
        if naxis < 2:
            print('ERROR\tread_pvfits: NAXIS of fits is < 2.')
            return
        self.naxis = naxis
        rng = range(1, naxis + 1)
        naxis_i  = np.array([int(header['NAXIS'+str(i)]) for i in rng])
        label_i  = np.array([header['CTYPE'+str(i)] for i in rng])
        refpix_i = np.array([int(header['CRPIX'+str(i)]) for i in rng])
        refval_i = np.array([header['CRVAL'+str(i)] for i in rng]) # degree
        if 'CDELT1' in header:
            del_i = np.array([header['CDELT'+str(i)] for i in rng]) # degree
        self.naxis_i  = naxis_i
        self.label_i  = label_i
        self.refpix_i = refpix_i
        self.refval_i = refval_i
        # beam size (degree)
        if multibeam:
            #self.read_multibeamtable()
            self.beam = self.multibeamtable.data
            # representative beam value
            # largest ones conservatively
            ichan = np.nanargmax(self.beam['BMAJ'])
            bmaj  = self.beam['BMAJ'][ichan]
            bmin  = self.beam['BMIN'][ichan]
            bpa   = self.beam['BPA'][ichan]
        elif 'BMAJ' in header:
            bmaj = header['BMAJ'] * 3600.  # arcsec
            bmin = header['BMIN'] * 3600.  # arcsec
            bpa  = header['BPA']  # degree
            self.beam = np.array([bmaj, bmin, bpa])
        else:
            bmaj      = None
            self.beam = None
        # Info. of P.A.
        if pa is not None:
            print(f'read_pvfits: Input P.A.: {pa:.1f} deg')
            self.pa = pa
        elif 'PA' in header:
            print('read_pvfits: Read P.A. in header.')
            self.pa = header['PA']
        elif 'P.A.' in header:
            print('read_pvfits: Read P.A. in header.')
            self.pa = header['P.A.']
        else:
            print('read_pvfits: No PA information is given.')
            self.pa = None
        # Resolution along offset axis
        if self.pa is None:
            self.res_off = bmaj
        else:
            if multibeam:
                res_offs = []
                for i in range(len(self.beam)):
                    bmaj, bmin, bpa, _, _ = self.beam[i]
                    res_offs.append(get_1dresolution(pa, bmaj, bmin, bpa))
                self.res_off = np.nanmax(res_offs)
            elif self.beam is not None:
                bmaj, bmin, bpa = self.beam
                self.res_off = get_1dresolution(pa, bmaj, bmin, bpa)
            else:
                self.res_off = None
        # rest frequency (Hz)
        if 'RESTFRQ' in header:
            restfreq = header['RESTFRQ']
        elif 'RESTFREQ' in header:
            restfreq = header['RESTFREQ']
        elif 'FREQ' in header:
            restfreq = header['FREQ']
        else:
            restfreq = None
        self.restfreq = restfreq
        # get axes
        ##### need to confirm what's rotation, as well as Yusuke's coding.
        # rotation of pixel coordinates
        if 'PC1_1' in header:
            pc_ij = np.array([
                [header[f'PC{i:d}_{j:d}']
                if f'PC{i:d}_{j:d}' in header else 0.
                for j in rng] for i in rng])
            pc_ij = pc_ij * np.array([del_i[i - 1] for i in rng])
        elif 'CD1_1' in header:
            pc_ij = np.array([[
                header[f'CD{i:d}_{j:d}']
                if f'CD{i:d}_{j:d}' in header else 0.
                for j in rng] for i in rng])
        else:
            print('CAUTION\tread_pvfits: '
                  + 'No keyword PCi_j or CDi_j are found. '
                  + 'No rotation is assumed.')
            pc_ij = np.array([[float(i==j) for j in rng] for i in rng])
            pc_ij = pc_ij * np.array([del_i[i - 1] for i in rng])
        # axes
        # +1 in i+1 comes from 0 start index in python
        axes = np.array([np.dot(pc_ij, (i+1 - refpix_i))
                         for i in range(np.max(naxis_i))]).T
        # x & v axes
        xaxis = axes[0]
        vaxis = axes[1]
        xaxis = xaxis[:naxis_i[0]]               # offset
        vaxis = vaxis[:naxis_i[1]] + refval_i[1] # frequency, absolute
        # check unit of offest
        if 'CUNIT1' in header:
            unit_i = np.array([header['CUNIT'+str(i)] for i in rng])
            if unit_i[0] in ['degree', 'deg']:
                # degree --> arcsec
                xaxis = xaxis * 3600.
                del_i[0] = del_i[0] * 3600.
        else:
            print('WARNING\tread_pvfits:: '
                  + 'No unit information in the header. '
                  + 'Assume the unit of the offset axis is arcesc.')
        # frequency --> velocity
        if label_i[1] in ['VRAD', 'VELO']:
            vaxis    = vaxis * 1.e-3 # m/s --> km/s
        else:
            print('read_pvfits: Convert frequency to velocity')
            vaxis = clight * (1. - vaxis/restfreq) # radio velocity c*(1-f/f0) [cm/s]
            vaxis = vaxis * 1.e-5                # cm/s --> km/s
        ##### what's saxis?
        if naxis == 2:
            saxis = None
        elif naxis == 3:
            saxis = axes[2]
            saxis = saxis[:naxis_i[2]]
        else:
            print('Error\tread_pvfits: naxis must be <= 3.')
        # get delta
        self.xaxis = xaxis
        self.vaxis = vaxis
        self.nx    = len(xaxis)
        self.nv    = len(vaxis)
        self.saxis = saxis
        self.delx  = xaxis[1] - xaxis[0]
        self.delv  = vaxis[1] - vaxis[0]


    # beam deconvolution
    def beam_deconvolution(self, sigmacut=None, 
        highfcut=2., solmode='gauss', fit_xlim=[], fit_vlim=[]):
        '''
        Deconvolve PV diagram with beam.

        Args
        ----
        sigmacut (float): Noise cut threshold given by absolute value.
        highfcut (float): Threshold to cut high-frequency component when slomode='nullcut'.
        solmode (str): Type of solution for the deconvolution. Must be either of 
         'nullcut', 'highfcut', 'gauss', 'taper' and 'spm'.
        '''
        # modules
        # modules for FFT
        from scipy.fft import fftshift, ifftn, fftn, fftfreq
        # 1D Gaussian function
        from .fitfuncs import gauss1d, gaussfit, complexgauss1d, complexgaussfit
        # to find positions
        from scipy.signal import argrelmin #, argrelmax

        # solutions
        def get_gaussiansolution_fc(nx, kx, d_deconv_fft, beam_fft):
            '''
            Get solution for deconvolution assuming that the solution is a Gaussian function.
            '''
            if (np.abs(d_deconv_fft[nx//2-1:nx//2+2]) == 0.).all():
                # if total flux is zeros
                return complexgauss1d(kx, 0., 0., 1., 0.,)
            else:
                # complex Gaussian fitting
                # initial estimate
                pini = [
                    np.abs(d_deconv_fft[nx//2]), # amp
                    0., # mean
                    np.nansum(np.abs(d_deconv_fft[nx//2-5:nx//2+6])*( kx[nx//2-5:nx//2+6] - 0.)**2. )\
                    /np.nansum(np.abs(d_deconv_fft[nx//2-5:nx//2+6])), # sigma
                    np.arctan2(d_deconv_fft[np.nanargmin(np.abs(kx))].real,
                    d_deconv_fft[np.nanargmin(np.abs(kx))].imag), # phase
                    ]
                param_opt, param_err = complexgaussfit(kx, d_deconv_fft, 1./beam_fft, pini=pini)
                if np.isnan(param_opt).any() == True:
                    return complexgauss1d(kx, 0., 0., 1., 0.,)
                else:
                    return complexgauss1d(kx, *param_opt)

        def get_gaussiansolution(_xin, _din, get_params=False):
            # exclude nan from the fitting
            _x = _xin[~np.isnan(_din)]
            _d = _din[~np.isnan(_din)]
            # if all zero
            if (_d == 0).all():
                if get_params:
                    return [0,0,0]
                else:
                    return np.zeros(len(_x))
            else:
                pout, _ = gaussfit(_x, _d, 1., [np.nanmax(_d), 
                    np.nansum(_d*_x)/np.nansum(_d), 
                    np.sqrt( np.nansum(_d*(np.nansum(_d*_x)/np.nansum(_d) - _x)**2)/np.nansum(_d) )])
                # return best-fit parameters
                if get_params:
                    return pout
                # or return gaussian
                if np.isnan(pout).any():
                    return np.zeros(len(_x))
                else:
                    return gauss1d(_x, *pout)

        def get_pointsolution(_x, _x0, _f):
            _indx = np.argmin(np.abs(_x - _x0))
            _pt = np.zeros(len(_x))
            _pt[_indx] = _f
            return _pt

        def zero_division(_a, _b):
            ans = np.empty(_a.shape)
            ans[_b != 0.] = _a[_b != 0.]/_b[_b != 0.]
            ans[ (_b == 0.) * (_a < 0.)] = - np.infty
            ans[ (_b == 0.) * (_a >= 0.)] = np.infty
            return ans

        # check axis
        if self.naxis == 2:
            shape = (self.nv, self.nx)
        elif self.naxis == 3:
            shape = (1, self.nv, self.nx)
        else:
            print('ERROR\tbeam_deconvolution: number of fits axes must be 2 or 3.')
            return -1

        # data
        data = np.squeeze(self.data.copy())
        xaxis = self.xaxis.copy()
        if len(fit_xlim) == 2:
            indx = np.nonzero((xaxis >= fit_xlim[0]) * (xaxis < fit_xlim[1]))[0]
            i_min, i_max = indx[0], indx[-1]
            data = data[:,i_min:i_max+1]
            xaxis = xaxis[indx]

        # cut data less than given threshold
        if sigmacut:
            data[data < sigmacut] = 0.

        # get one dimensional beam size for deconvolution
        if self.multibeam:
            if self.pa is not None:
                res_off = np.array([
                    get_1dresolution(
                        self.pa, self.beam[i][0], 
                        self.beam[i][1], self.beam[i][2])
                    for i in range(self.nv)
                    ])
            else:
                res_off = self.beam[:,0] # get bmaj
        else:
            res_off = self.res_off
        sigma_beam_fft = (2.*np.sqrt(2.*np.log(2.)))/(res_off*np.pi*2.)

        # analytical solution
        if solmode == 'gauss':
            # get Gaussian solution in real space
            g_ = np.array([
                get_gaussiansolution(xaxis, d_i, get_params=True) 
                if np.nanmax(d_i) >= sigmacut
                else [0., 0., 0.]
                for d_i in data
                ])
            g_a   = g_[:,0]
            g_mn  = g_[:,1]
            g_sig = g_[:,2]

            # replace negative amplitude and cases that the fitting fails with zero
            for gi in g_.T:
                gi[ (g_a < 0.) | (np.isnan(gi)) ] = 0.

            # deconvolution
            g_deconv_sig2 = (2.*np.pi*g_sig)**2 - (1./sigma_beam_fft)**2 # 2 pi is necessary as FT of x is k (not omega)
            g_deconv_sig2[g_deconv_sig2 < 0.] = 0. # diverge
            g_deconv_sig = np.sqrt(g_deconv_sig2)/(2.*np.pi)
            g_deconv_a  = zero_division(g_a*g_sig, g_deconv_sig)
            g_deconv_mn = g_mn
            #print ([g_deconv_a, g_deconv_mn, g_deconv_sig])

            d_deconv = np.array([
                gauss1d(self.xaxis, g_deconv_a[i], g_deconv_mn[i], g_deconv_sig[i]) 
                if g_deconv_sig[i] != 0.
                else get_pointsolution(self.xaxis, g_deconv_mn[i], 
                    g_a[i]*np.sqrt(2.*np.pi)*g_deconv_sig[i])
                for i in range(self.nv)
                ])
            # Jy/beam --> Jy/pixel
            beam_area = np.sqrt(2.*np.pi)*res_off/(2.*np.sqrt(2*np.log(2))) # 1D beam area
            if self.multibeam:
                d_deconv /= np.tile(beam_area, (self.nv, 1))/self.delx
            else:
                d_deconv /= beam_area/self.delx
            self.data_deconv = d_deconv.reshape(shape)
        else:
            # numerical solutions
            # beam array
            nv, nx = self.nv, self.nx
            if self.multibeam:
                beam = np.empty((nv,nx))
                for i in range(len(self.beam)):
                    bmaj, bmin, bpa, _, _ = self.beam[i]
                    if self.pa != None:
                        res_off = get_1dresolution(self.pa, bmaj, bmin, bpa)
                    else:
                        res_off = bmaj
                    beam[i, :] = gauss1d(self.xaxis, 1., 0., res_off/(2.*np.sqrt(2.*np.log(2.))))
                    beam[i, :] /= np.sum(beam[i, :]) # normalize
            elif self.res_off != None:
                _beam = gauss1d(self.xaxis, 1., 0., self.res_off/(2.*np.sqrt(2.*np.log(2.))))
                #_beam = np.r_[_beam, np.zeros(_beam.shape[0]-1)] # zero-padding
                _beam /= np.sum(_beam) # normalize
                beam = np.tile(_beam, (nv,1))
            else:
                print('ERROR\tbeam_deconvolution: angular resolution is not given correctly.')
                print('ERROR\tbeam_deconvolution: check the header of the input fits file.')
                return -1

            # FFT
            #nx_fft = nx*2 - 1 # take into account zero-padding
            kx   = fftshift(fftfreq(nx, self.delx))
            kv   = fftshift(fftfreq(nv, self.delv))
            kkx, kkv = np.meshgrid(kx, kv)
            beam_fft = fftshift(fftn(beam, axes=(1,)), axes=(1,))
            data_fft = fftshift(fftn(data, axes=(1,)), axes=(1,))

            d_deconv_fft = data_fft/beam_fft

            # fillter
            if solmode == 'nullcut':
                # based on null
                for i in range(nv):
                    d_fft_1d   = np.abs(data_fft[i,:][nx//2:])
                    first_null = argrelmin(d_fft_1d)[0][0]\
                     if len(argrelmin(d_fft_1d)[0]) > 0 else -1
                    fx_null    = kx[nx//2:][first_null]
                    d_deconv_fft[i, (np.abs(kkx) > fx_null)[1]] = 0.+0.j # drop highfreq. components

                    if highfcut != None:
                        if fx_null > sigma_beam_fft*highfcut:
                            d_deconv_fft[i, (np.abs(kkx) >\
                             sigma_beam_fft*highfcut)[1]] = 0.+0.j # drop highfreq. components
            elif solmode == 'highfcut':
                if highfcut == None:
                    print('ERROR\tbeam_deconvolution: Give valid highfcut when solmode=highfcut.')
                    return -1
                # drop highfreq. components
                d_deconv_fft[(np.abs(kkx) > sigma_beam_fft*highfcut)] = 0.+0.j
            elif solmode == 'gauss-fc':
                # deconvolution
                d_deconv_fft = np.array([
                        get_gaussiansolution_fc(nx, kx, d_deconv_fft[i,:], beam_fft[i,:]) 
                        for i in range(nv)])
                #elif solmode == 'gauss':
                # Numerical solution
                #g_ = np.array([
                #    get_gaussiansolution(self.xaxis, d_i) for d_i in data
                #    ]) # get Gaussian solution in real space
                #g_fft = fftshift(fftn(g_, axes=(1,)), axes=(1,))
                #d_deconv_fft = g_fft/beam_fft
                #d_deconv_fft = np.array([
                #    i if np.abs(i[nx//2]) >= np.abs(i[(3*nx)//4]) else np.full(len(self.xaxis), i[nx//2])
                #    for i in d_deconv_fft
                #    ]) # force to be flat
            elif solmode == 'taper':
                if highfcut == None:
                    print('ERROR\tbeam_deconvolution: Give valid highfcut when solmode=taper.')
                    return -1
                _taper_beam = gauss1d(kx, 1., 0., sigma_beam_fft*highfcut)
                #_taper_beam /= np.sum(_taper_beam) # normalize
                taper_beam = np.tile(_taper_beam, (nv,1))
                d_deconv_fft *= taper_beam
            else:
                print('WARNING\tbeam_deconvolution: Given solmode parameter is not valid.')
                return 0

            # IFFT
            d_deconv = np.abs(fftshift(ifftn(d_deconv_fft, axes=(1,)), axes=(1,)))
            d_deconv = d_deconv.reshape(shape)
            self.data_deconv = d_deconv

    # Draw pv diagram
    def draw_pvdiagram(self,outname,data=None,header=None,ax=None,outformat='pdf',color=True,cmap='Greys',
        vmin=None,vmax=None,vsys=None,contour=True,clevels=None,ccolor='k',
        vrel=False,logscale=False,x_offset=False,ratio=1.2, prop_vkep=None,fontsize=14,
        lw=1,clip=None,plot_res=True,inmode='fits',xranges=[], yranges=[],
        ln_hor=True, ln_var=True, alpha=None):
        '''
        Draw a PV diagram.

        Args:
         - outname:
        '''

        # Modules
        import copy
        import matplotlib as mpl

        # format
        formatlist = np.array(['eps','pdf','png','jpeg'])

        # properties of plots
        #mpl.use('Agg')
        plt.rcParams['font.family']     = 'Arial' # font (Times New Roman, Helvetica, Arial)
        plt.rcParams['xtick.direction'] = 'in'   # directions of x ticks ('in'), ('out') or ('inout')
        plt.rcParams['ytick.direction'] = 'in'   # directions of y ticks ('in'), ('out') or ('inout')
        plt.rcParams['font.size']       = fontsize  # fontsize

        def change_aspect_ratio(ax, ratio):
            '''
            This function change aspect ratio of figure.
            Parameters:
                ax: ax (matplotlit.pyplot.subplots())
                    Axes object
                ratio: float or int
                    relative x axis width compared to y axis width.
            '''
            aspect = (1/ratio) *(ax.get_xlim()[1] - ax.get_xlim()[0]) / (ax.get_ylim()[1] - ax.get_ylim()[0])
            aspect = np.abs(aspect)
            aspect = float(aspect)
            ax.set_aspect(aspect)


        # output file
        if (outformat == formatlist).any():
            outname = outname + '.' + outformat
        else:
            print('ERROR\tdraw_pvdiagram: Outformat is wrong.')
            return

        # Input
        if inmode == 'data':
            if data is None:
                print('inmode ="data" is selected.'
                      + 'data must be provided.')
                return
            naxis = len(data.shape)
        else:
            data   = self.data
            header = self.header
            naxis  = self.naxis


        # figures
        if ax:
            pass
        else:
            fig = plt.figure(figsize=(11.69,8.27)) # figsize=(11.69,8.27)
            ax  = fig.add_subplot(111)

        # Read
        xaxis = self.xaxis
        vaxis = self.vaxis
        delx  = self.delx
        delv  = self.delv
        res_off = self.res_off


        # relative velocity or LSRK
        offlabel = r'$\mathrm{Offset\ (arcsec)}$'
        if vrel:
            vaxis   = vaxis - vsys
            vlabel  = r'$\mathrm{Relative\ velocity\ (km\ s^{-1})}$'
            #vcenter = 0
        else:
            vlabel  = r'$\mathrm{LSR\ velocity\ (km\ s^{-1})}$'
            #vcenter = vsys


        # set extent of an image
        offmin = xaxis[0] - delx*0.5
        offmax = xaxis[-1] + delx*0.5
        velmin = vaxis[0] - delv*0.5
        velmax = vaxis[-1] + delv*0.5


        # set axes
        if x_offset:
            data   = data[0,:,:]
            extent = (offmin,offmax,velmin,velmax)
            xlabel = offlabel
            ylabel = vlabel
            #hline_params = [vsys,offmin,offmax]
            #vline_params = [0.,velmin,velmax]
            #ln_hor = True if vsys else False
            res_x = res_off
            res_y = delv
        else:
            #data   = np.rot90(data[0,:,:])
            data   = data[0,:,:].T
            extent = (velmin,velmax,offmin,offmax)
            xlabel = vlabel
            ylabel = offlabel
            #hline_params = [0.,velmin,velmax]
            #vline_params = [vsys,offmin,offmax]
            #ln_var = True if vsys else False
            res_x = delv
            res_y = res_off


        # set colorscale
        if vmax:
            pass
        else:
            vmax = np.nanmax(data)


        # logscale
        if logscale:
            norm = mpl.colors.LogNorm(vmin=vmin,vmax=vmax)
        else:
            norm = mpl.colors.Normalize(vmin=vmin,vmax=vmax)


        # clip data at some value
        data_color = copy.copy(data)
        if clip:
            data_color[np.where(data < clip)] = np.nan

        # plot images
        if color:
            imcolor = ax.imshow(data_color, cmap=cmap, origin='lower',
                extent=extent, norm=norm, alpha=alpha)

        if contour:
            imcont  = ax.contour(data, colors=ccolor, origin='lower',
                extent=extent, levels=clevels, linewidths=lw, alpha=alpha)


        # axis labels
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)

        # set xlim, ylim
        if len(xranges) == 0:
            ax.set_xlim(extent[0],extent[1])
        elif len(xranges) == 2:
            xmin, xmax = xranges
            ax.set_xlim(xmin, xmax)
        else:
            print('WARRING: Input xranges is wrong.'
                   + 'Must be [xmin, xmax].')
            ax.set_xlim(extent[0],extent[1])

        if len(yranges) == 0:
            ax.set_ylim(extent[2],extent[3])
        elif len(yranges) == 2:
            ymin, ymax = yranges
            ax.set_ylim(ymin, ymax)
        else:
            print('WARRING: Input yranges is wrong.'
                   + 'Must be [ymin, ymax].')
            ax.set_ylim(extent[2],extent[3])


        # lines showing offset 0 and relative velocity 0
        #if ln_hor:
        #    xline = plt.hlines(*hline_params, ccolor,
        #                       linestyles='dashed', linewidths=1.)
        #if ln_var:
        #    yline = plt.vlines(*vline_params, ccolor,
        #                       linestyles='dashed', linewidths=1.)

        ax.tick_params(which='both', direction='in', bottom=True,
                       top=True, left=True, right=True, pad=9)

        # plot resolutions
        if plot_res:
            # x axis
            #print(res_x, res_y)
            res_x_plt, res_y_plt \
                = ax.transLimits.transform((res_x*0.5, res_y*0.5)) \
                    -  ax.transLimits.transform((0, 0)) # data --> Axes coordinate
            ax.errorbar(0.1, 0.1, xerr=res_x_plt, yerr=res_y_plt,
                        color=ccolor, capsize=3, capthick=1.,
                        elinewidth=1., transform=ax.transAxes)

        # aspect ratio
        if ratio:
            change_aspect_ratio(ax, ratio)

        # save figure
        plt.savefig(outname, transparent=True)

        return ax


# Get one dimensional resolution
def get_1dresolution(pa, bmaj, bmin, bpa):
    '''Calculate one dimensional spatial resolution along a cut with P.A.=pa

    An ellipse of the beam
        (x/bmin)**2 + (y/bmaj)**2 = 1
        y = x*tan(theta)
        --> beam width in the direction of pv cut (P.A.=pa)

    Args:
        pa (float): Position angle of a one dimensional cut (degree).
        bmaj (float): Major beam size.
        bmin (float): Minor beam size.
        bpa (float): Position angle of the beam.
    '''
    del_pa = np.radians(pa - bpa)
    term2 = np.hypot(np.sin(del_pa) / bmin, np.cos(del_pa) / bmaj)
    return (1. / term2)