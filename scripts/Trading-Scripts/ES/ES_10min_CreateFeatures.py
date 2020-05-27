import pandas as pd
import numpy as np
import datetime
from pandas.tseries.holiday import USFederalHolidayCalendar as calendar
import configparser
import warnings
import feather
import time
from multiprocessing import Pool, Process


start_time = time.time()


config = configparser.ConfigParser()
config.read('/home/melgazar9/Trading/TD/Scripts/Trading-Scripts/ES/scripts/ES_10min_CreateFeatures.ini')

min_lookback = int(config['PARAMS']['min_lookback'])
max_lookback = int(config['PARAMS']['max_lookback']) + 1
lookback_increment = int(config['PARAMS']['lookback_increment'])



def get_df_init(df, timeframe):

    df_ohlc = df.resample(timeframe).ohlc()
    df_volume = df['5minVolume'].resample(timeframe).sum()

    df_resampled = pd.DataFrame()
    df_resampled[timeframe + 'Open'] = df_ohlc['5minOpen']['open']
    df_resampled[timeframe + 'High'] = df_ohlc['5minHigh']['high']
    df_resampled[timeframe + 'Low'] = df_ohlc['5minLow']['low']
    df_resampled[timeframe + 'Close'] = df_ohlc['5minClose']['close']
    df_resampled[timeframe + 'Move'] = df_ohlc['5minClose']['close'] - df_ohlc['5minOpen']['open']
    df_resampled[timeframe + 'Range'] = df_ohlc['5minHigh']['high'] - df_ohlc['5minLow']['low']
    df_resampled[timeframe + 'HighMove'] = df_ohlc['5minHigh']['high'] - df_ohlc['5minOpen']['open']
    df_resampled[timeframe + 'LowMove'] = df_ohlc['5minLow']['low'] - df_ohlc['5minOpen']['open']
    df_resampled[timeframe + 'Volume'] = df_volume

    return df_resampled


def get_rolling_features(df, col, window, min_periods):

    df[col + 'Rolling' + str('Sum').strip('()') + '_Window' + str(window)] = df[col].rolling(window=window, min_periods=min_periods).sum()
    df[col + 'Rolling' + str('Mean').strip('()') + '_Window' + str(window)] = df[col].rolling(window=window, min_periods=min_periods).mean()
    df[col + 'Rolling' + str('Std').strip('()') + '_Window' + str(window)] = df[col].rolling(window=window, min_periods=min_periods).std()
    df[col + 'Rolling' + str('Max').strip('()') + '_Window' + str(window)] = df[col].rolling(window=window, min_periods=min_periods).max()
    df[col + 'Rolling' + str('Min').strip('()') + '_Window' + str(window)] = df[col].rolling(window=window, min_periods=min_periods).min()

    return df

def macd(df, features, nslow, nfast):

    for feature in features:
        df[feature+'MACD_'+str(nslow)+'-'+str(nfast)] = df[feature].ewm(span=nslow, adjust=True).mean() - df[feature].ewm(span=nfast, adjust=True).mean() # 26 -12 period
        df[feature+'9dMA_'+str(nslow)+'-'+str(nfast)] = df[feature+'MACD_'+str(nslow)+'-'+str(nfast)].rolling(window=9).mean()
    return df


def RSI(series, period):

    delta = series.diff().dropna()
    u = delta * 0
    d = u.copy()
    u[delta > 0] = delta[delta > 0]
    d[delta < 0] = -delta[delta < 0]
    u[u.index[period-1]] = np.mean( u[:period] ) # first value is sum of avg gains
    u = u.drop(u.index[:(period-1)])
    d[d.index[period-1]] = np.mean( d[:period] ) # first value is sum of avg losses
    d = d.drop(d.index[:(period-1)])
    rs = u.ewm(com=period-1, adjust=False).mean() / d.ewm(com=period-1, adjust=False).mean()
    rsi = pd.DataFrame(100 - 100 / (1 + rs)).rename(columns={series.name : str(series.name).strip('Close')+'RSI'})

    #df = pd.merge_asof(df, rsi, )
    return rsi


def ATR(df, feature):
    df[feature[0:-5]+'ATR'] = df[feature].ewm(span=10).mean()
    df[feature[0:-5]+'ATR'] = (df[feature[0:-5]+'ATR'].shift(1)*13 + df[feature]) /  14

    return df

def Bollinger_Bands(df, feature, window_size, num_of_std):

    rolling_mean = df[feature].rolling(window=window_size).mean()
    rolling_std  = df[feature].rolling(window=window_size).std()
    upper_band = rolling_mean + (rolling_std*num_of_std)
    lower_band = rolling_mean - (rolling_std*num_of_std)

    upper_band = pd.DataFrame(upper_band, index=upper_band.index).rename(columns={feature : feature+'UpperBB'})
    lower_band = pd.DataFrame(lower_band, index=lower_band.index).rename(columns={feature : feature+'LowerBB'})


    temp = pd.merge_asof(df, upper_band, left_index=True, right_index=True)
    temp = pd.merge_asof(temp, lower_band, left_index=True, right_index=True)

#     temp =  Bollinger_Bands(df, 'Prev10minClose', 20, 2)
    price_upperBB_diff = df[feature] - temp[feature+'UpperBB']
    price_lowerBB_diff = df[feature] - temp[feature+'LowerBB']
    temp[feature.strip('Close')+'Price-UpperBB_diff'] = price_upperBB_diff
    temp[feature.strip('Close')+'Price-LowerBB_diff'] = price_lowerBB_diff

    temp[feature.strip('Close')+'UpperBB_Change'] = temp[feature+'UpperBB'].diff()#.rename(columns={feature+'UpperBB':feature+'UpperBB_Change'})
    temp[feature.strip('Close')+'LowerBB_Change'] = temp[feature+'LowerBB'].diff()


    temp.drop([feature+'UpperBB'], axis=1, inplace=True)
    temp.drop([feature+'LowerBB'], axis=1, inplace=True)

    return temp


def PPSR(df, high, low, close):

    PP_10min = pd.Series((df['Prev10minHigh'] + df['Prev10minLow'] + df['Prev10minClose']) / 3)
    S1_10min = pd.Series(2 * PP_10min - df['Prev10minHigh'])
    R1_10min = pd.Series(2 * PP_10min - df['Prev10minLow'])
    R2_10min = pd.Series(PP_10min + df['Prev10minHigh'] - df['Prev10minLow'])
    S2_10min = pd.Series(PP_10min - df['Prev10minHigh'] + df['Prev10minLow'])
    R3_10min = pd.Series(df['Prev10minHigh'] + 2 * (PP_10min - df['Prev10minLow']))
    S3_10min = pd.Series(df['Prev10minLow'] - 2 * (df['Prev10minHigh'] - PP_10min))
    psr_10min = {'PP': PP_10min, 'S1': S1_10min, 'R1': R1_10min, 'S2': S2_10min, 'R2': R2_10min, 'S3': S3_10min, 'R3': R3_10min}
    PSR_10min = pd.DataFrame(psr_10min).rename(columns={'PP':'Prev10minPP',
                                                        'S1':'Prev10minS1',
                                                        'R1':'Prev10minR1',
                                                        'S2':'Prev10minS2',
                                                        'R2':'Prev10minR2',
                                                        'S3':'Prev10minS3',
                                                        'R3':'Prev10minR3'})
    if high == 'Prev10minHigh':
        return PSR_10min


    PP = pd.Series((df[high] + df[low] + df[close]) / 3)
    S1 = pd.Series(2 * PP - df[high])
    R1 = pd.Series(2 * PP - df[low])
    R2 = pd.Series(PP + df[high] - df[low])
    S2 = pd.Series(PP - df[high] + df[low])
    R3 = pd.Series(df[high] + 2 * (PP - df[low]))
    S3 = pd.Series(df[low] - 2 * (df[high] - PP))
    psr = {'PP': PP, 'S1': S1, 'R1': R1, 'S2': S2, 'R2': R2, 'S3': S3, 'R3': R3}
    PSR = pd.DataFrame(psr).rename(columns={'PP':low.strip('Low')+'PP',
                                            'S1':low.strip('Low')+'S1',
                                            'R1':low.strip('Low')+'R1',
                                            'S2':low.strip('Low')+'S2',
                                            'R2':low.strip('Low')+'R2',
                                            'S3':low.strip('Low')+'S3',
                                            'R3':low.strip('Low')+'R3'})




    temp = pd.merge_asof(PSR_10min, PSR, left_index=True, right_index=True)

    temp[low.strip('Low')+'PP_Change'] = temp[low.strip('Low')+'PP'] - temp['Prev10minPP']
    temp[low.strip('Low')+'S1_Change'] = temp[low.strip('Low')+'S1'] - temp['Prev10minS1']
    temp[low.strip('Low')+'R1_Change'] = temp[low.strip('Low')+'R1'] - temp['Prev10minR1']
    temp[low.strip('Low')+'S2_Change'] = temp[low.strip('Low')+'S2'] - temp['Prev10minS2']
    temp[low.strip('Low')+'R2_Change'] = temp[low.strip('Low')+'R2'] - temp['Prev10minR2']
    temp[low.strip('Low')+'S3_Change'] = temp[low.strip('Low')+'S3'] - temp['Prev10minS3']
    temp[low.strip('Low')+'R3_Change'] = temp[low.strip('Low')+'R3'] - temp['Prev10minR3']

    temp = temp[[i for i in temp.columns if i.endswith('Change')]]

    return temp



def main():

    df_5min = pd.read_csv(config['PATH']['read_file'])
    df_5min.set_index('Datetime', inplace=True)
    df_5min.index = pd.to_datetime(df_5min.index)


    ####################################################
    #                 Rewritten Code Here
    ####################################################

    dfs = {f'{i}min' : get_df_init(df_5min, f'{i}min') for i in range(min_lookback, max_lookback, lookback_increment)}

    for i in range(min_lookback, max_lookback, lookback_increment):
        dfs[f'{i}min'].index = pd.Series(dfs[f'{i}min'].index).shift(-1)
        dfs[f'{i}min'] = dfs[f'{i}min'].loc[dfs[f'{i}min'].index.to_series().dropna()]
        dfs[f'{i}min'].sort_index(inplace=True)


    df = pd.merge_asof(dfs['5min'], dfs['10min'], left_index=True, right_index=True)
    for i in range(min_lookback + 10, max_lookback, lookback_increment):
        df = pd.merge_asof(df, dfs[f'{i}min'], left_index=True, right_index=True)


    df = df.add_prefix('Prev')

    if config['PARAMS']['keep_5min_candlesticks'] == 'FALSE':
        df = df[[i for i in df.columns if not i.startswith('Prev5min')]]
        df = df.resample('10min').first()

    elif config['PARAMS']['keep_5min_candlesticks'] == 'TRUE':
        pass
        #print(df[[i for i in df.columns if i.startswith('Prev5min')]])
    df.dropna(inplace=True)
    # print(df[[i for i in df.columns if i.startswith('Prev15min')]])


    cal = calendar()
    dr = pd.date_range(start=df.index[0], end=df.index[-1])
    holidays = cal.holidays(start=dr.min(), end=dr.max())
    df['IsHoliday'] = df.index.isin(holidays)
    df['Year'] = df.index.year
    df['Month'] = df.index.month
    df['Week'] = df.index.week
    df['Day'] = df.index.day
    df['DayofWeek'] = df.index.dayofweek
    df['DayofYear'] = df.index.dayofyear
    df['IsMonthStart'] = df.index.is_month_start
    df['IsMonthEnd'] = df.index.is_month_end
    df['IsQuarterStart'] = df.index.is_quarter_start
    df['IsQuarterEnd'] = df.index.is_quarter_end
    df['IsYearStart'] = df.index.is_year_start
    df['IsYearEnd'] = df.index.is_year_end
    df['Hour'] = df.index.hour
    df['Quarter'] = df.index.quarter



    for col in df[[i for i in df.columns if i.endswith('Move') or i.endswith('Volume')]].columns:
        df = get_rolling_features(df, col, 4, 1)

    df = macd(df, [i for i in df.columns if i.endswith('Close')], 12, 26)


    for col in [i for i in df.columns if i.endswith('Close')]:
        df = pd.merge_asof(df, RSI(df[col], 14), left_index=True, right_index=True)


    for i in [i for i in df.columns if i.endswith('Range')]:
        df = ATR(df, col)


    for col in [i for i in df.columns if i.endswith('Close')]:
        df = Bollinger_Bands(df, col, 20, 2)


    ppsrs = {f'{i}min' : PPSR(df, 'Prev' + f'{i}min' + 'High', 'Prev' + f'{i}min' + 'Low', 'Prev' + f'{i}min' + 'Close') for i in range(min_lookback + 5, max_lookback, lookback_increment)}
    temp = pd.merge_asof(ppsrs['10min'], ppsrs['15min'], left_index=True, right_index=True)
    for i in range(min_lookback + 15, max_lookback, lookback_increment):
        temp = pd.merge_asof(temp, ppsrs[f'{i}min'], left_index=True, right_index=True)



    temp_10min_change = temp[[i for i in temp.columns if i.startswith('Prev10min')]].diff().rename(columns={'Prev10minPP': 'Prev10minPP_Change',
                                                                                                            'Prev10minS1': 'Prev10minS1_Change',
                                                                                                            'Prev10minR1': 'Prev10minR1_Change',
                                                                                                            'Prev10minS2': 'Prev10minS2_Change',
                                                                                                            'Prev10minR2': 'Prev10minR2_Change',
                                                                                                            'Prev10minS3': 'Prev10minS3_Change',
                                                                                                            'Prev10minR3': 'Prev10minR3_Change'})
    temp.drop(['Prev10minPP','Prev10minS1','Prev10minR1','Prev10minS2','Prev10minR2','Prev10minS3','Prev10minR3'], axis=1, inplace=True)
    df = pd.merge_asof(df, temp, left_index=True, right_index=True)
    df = pd.merge_asof(df, temp_10min_change, left_index=True, right_index=True)

    df.drop(['Prev10minPP_Change', 'Prev10minS1_Change','Prev10minR1_Change',
             'Prev10minS2_Change','Prev10minR2_Change', 'Prev10minS3_Change','Prev10minR3_Change'],
             axis=1, inplace=True)



    important_cols = [i for i in df.columns if not i.endswith('Open') and not i.endswith('High') and not
                      i.endswith('Low') and not i.endswith('Close')]


    df = df[important_cols]
    df.dropna(inplace=True)

    try:
        df.drop(['Actual10minMoveRollingSum_Window4',
                 'Actual10minMoveRollingMean_Window4',
                 'Actual10minMoveRollingStd_Window4',
                 'Actual10minMoveRollingMax_Window4',
                 'Actual10minMoveRollingMin_Window4'], axis=1, inplace=True)

    except:
        pass

    print([i for i in df.columns if i.startswith('Actual')])
    print(df)
    # print(list(df.columns))
    if config['PARAMS']['save_df'] == 'TRUE':
        if config['PARAMS']['feather'] == 'FALSE':
            df.to_csv(config['PATH']['save_df_path'] + config['PARAMS']['product'] + '_10min_FULL_' + str(datetime.datetime.today().date()) + '.csv')
        elif config['PARAMS']['feather'] == 'TRUE':
            df.reset_index(inplace=True)
            feather.write_dataframe(df, config['PATH']['save_df_path'] + config['PARAMS']['product'] + '_10min_FULL_' + str(datetime.datetime.today().date()) + '.feather')

    return

if __name__ == '__main__':
    main()
    print(time.time()-start_time)
    # p = Process(target=main)
    # p.start()
    # p.join()
    # print(time.time() - start_time)

    # with Pool(32) as p: # This doesn't speed up the script at all
    #     p.map(main, [1])
    #     # main()
    #     end_time = time.time()
    #     print(end_time - start_time)
    #     print('Script took:', end_time - start_time)
