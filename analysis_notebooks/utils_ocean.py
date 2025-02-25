import traceback
import warnings

import numpy as np
import xarray as xr

import os
import subprocess
import tempfile


nmols_to_PgCyr = 1e-9 * 86400. * 365. * 12e-15


def global_mean(ds, normalize=True, include_ms=False):
    """
    Compute the global mean on a POP dataset. 
    Return computed quantity in conventional units.
    """

    compute_vars = [
        v for v in ds 
        if 'time' in ds[v].dims and ('nlat', 'nlon') == ds[v].dims[-2:]
    ]
    other_vars = list(set(ds.variables) - set(compute_vars))

    if include_ms:
        surface_mask = ds.TAREA.where(ds.KMT > 0).fillna(0.)
    else:
        surface_mask = ds.TAREA.where(ds.REGION_MASK > 0).fillna(0.)        
    
    masked_area = {
        v: surface_mask.where(ds[v].notnull()).fillna(0.) 
        for v in compute_vars
    }

    with xr.set_options(keep_attrs=True):
        
        dso = xr.Dataset({
            v: (ds[v] * masked_area[v]).sum(['nlat', 'nlon'])
            for v in compute_vars
        })
        if normalize:
            dso = xr.Dataset({
                v: dso[v] / masked_area[v].sum(['nlat', 'nlon'])
                for v in compute_vars
            })            
        else:
            for v in compute_vars:
                if v in variable_defs.C_flux_vars:
                    dso[v] = dso[v] * nmols_to_PgCyr
                    dso[v].attrs['units'] = 'Pg C yr$^{-1}$'
                
        return xr.merge([dso, ds[other_vars]]).drop(
            [c for c in ds.coords if ds[c].dims == ('nlat', 'nlon')]
        )
    
    
def adjust_pop_grid(tlon,tlat,field):
    nj = tlon.shape[0]
    ni = tlon.shape[1]
    xL = int(ni/2 - 1)
    xR = int(xL + ni)

    tlon = np.where(np.greater_equal(tlon,min(tlon[:,0])),tlon-360.,tlon)
    lon  = np.concatenate((tlon,tlon+360.),1)
    lon = lon[:,xL:xR]

    if ni == 320:
        lon[367:-3,0] = lon[367:-3,0]+360.
    lon = lon - 360.
    lon = np.hstack((lon,lon[:,0:1]+360.))
    if ni == 320:
        lon[367:,-1] = lon[367:,-1] - 360.

    #-- trick cartopy into doing the right thing:
    #   it gets confused when the cyclic coords are identical
    lon[:,0] = lon[:,0]-1e-8
    
    #-- periodicity
    lat  = np.concatenate((tlat,tlat),1)
    lat = lat[:,xL:xR]
    lat = np.hstack((lat,lat[:,0:1]))

    field = np.ma.concatenate((field,field),1)
    field = field[:,xL:xR]
    field = np.ma.hstack((field,field[:,0:1]))
    return lon,lat,field


def normal_lons(lons):

    lons_norm=np.full((len(lons.nlat), len(lons.nlon)), np.nan)

    lons_norm_firstpart = lons.where(lons<=180.)
    lons_norm_secpart = lons.where(lons>180.) - 360.

    lons_norm_firstpart = np.asarray(lons_norm_firstpart)
    lons_norm_secpart = np.asarray(lons_norm_secpart)

    lons_norm[~np.isnan(lons_norm_firstpart)] = lons_norm_firstpart[~np.isnan(lons_norm_firstpart)]
    lons_norm[~np.isnan(lons_norm_secpart)] = lons_norm_secpart[~np.isnan(lons_norm_secpart)]

    lons_norm=xr.DataArray(lons_norm)
    lons_norm=lons_norm.rename({'dim_0':'nlat'})
    lons_norm=lons_norm.rename({'dim_1':'nlon'})
    
    return(lons_norm)


def calc_area(nx,ny,lats):

    area = xr.DataArray(np.zeros([ny,nx]), dims=('lat','lon'))

    j=0

    for lat in lats:

        pi     =    3.14159265359
        radius = 6378.137

        deg2rad = pi / 180.0

        resolution_lat =1./12. #res in degrees
        resolution_lon =1./12. #res in degrees

        elevation = deg2rad * (lat + (resolution_lat / 2.0))

        deltalat = deg2rad * resolution_lon
        deltalon = deg2rad * resolution_lat

        area[j,:] = (2.0*radius**2*deltalon*np.cos(elevation)*np.sin((deltalat/2.0)))

        j = j + 1

    return(area)

def zonal_mean_via_fortran(ds, var, grid=None, rmask_file=None):
    """
    Write ds to a temporary netCDF file, compute zonal mean for
    a given variable based on Keith L's fortran program, read
    resulting netcdf file, and return the new xarray dataset
    If three_ocean_regions=True, use a region mask that extends the
    Pacific, Indian, and Atlantic to the coast of Antarctica (and does
    not provide separate Arctic Ocean, Lab Sea, etc regions)
    """

    # xarray doesn't require the ".nc" suffix, but it's useful to know what the file is for
    ds_in_file = tempfile.NamedTemporaryFile(suffix='.nc')
    ds_out_file = tempfile.NamedTemporaryFile(suffix='.nc')
    ds.to_netcdf(ds_in_file.name, format = 'NETCDF4')
    print(f'Wrote dataset to {ds_in_file.name}')

    # Set up location of the zonal average executable
    za_exe = os.path.join(os.path.sep,
                          'glade',
                          'u',
                          'home',
                          'klindsay',
                          'bin',
                          'zon_avg',
                          'za')
    if grid:
        # Point to a file that contains all necessary grid variables
        # I think that is KMT, TLAT, TLONG, TAREA, ULAT, ULONG, UAREA, and REGION_MASK
        if grid == 'gx1v7':
            grid_file = '/glade/derecho/scratch/kristenk/POP_gx1v7.nc'
        else:
            print(f'WARNING: no grid file for {grid}, using xarray dataset for grid vars')
            grid_file = ds_in_file.name
    else:
        # Assume xarray dataset contains all needed fields
        grid_file = ds_in_file.name
    if rmask_file:
        region_mask = ['-rmask_file', rmask_file]
    else:
        region_mask = []

    # Set up the call to za with correct options
    za_call = [za_exe,
               '-v', var] + \
              region_mask + \
              [
               '-grid_file', grid_file,
               '-kmt_file', grid_file,
               '-O', '-o', ds_out_file.name, # -O overwrites existing file, -o gives file name
               ds_in_file.name]

    # Use subprocess to call za, allows us to capture stdout and print it
    proc = subprocess.Popen(za_call, stdout=subprocess.PIPE)
    (out, err) = proc.communicate()
    if not out:
        # Read in the newly-generated file
        print('za ran successfully, writing netcdf output')
        ds_out = xr.open_dataset(ds_out_file.name)
    else:
        print(f'za reported an error:\n{out.decode("utf-8")}')

    # Delete the temporary files and return the new xarray dataset
    ds_in_file.close()
    ds_out_file.close()
    if not out:
        return(ds_out)
    return(None)