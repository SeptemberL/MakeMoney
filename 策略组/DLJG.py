def translate_mylanguage_macd_divergence(df):
    """
    将给定的包含 'Close' 列的 Pandas DataFrame 转换为包含 MACD 相关指标和背离信号的 DataFrame。
    """

    # === MACD 指标计算 ===
    ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = 100 * (ema_12 - ema_26)
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD'] = (df['DIF'] - df['DEA']) * 2

    # === 底部结构预警 ===
    df['死叉'] = (df['DEA'] > df['DIF']) & (df['DEA'].shift(1) <= df['DIF'].shift(1))
    df['N1'] = df['死叉'].rolling(window=len(df), min_periods=1).apply(lambda x: np.where(x[::-1])[0][0] if np.any(x) else np.nan, raw=True)

    def ref_series(series, periods):
        if isinstance(periods, pd.Series):
            shifted_series = pd.Series(index=series.index, dtype=series.dtype)
            for i, period in periods.items():
                if pd.notna(period):
                    if isinstance(i, pd.Timestamp):
                        delta = pd.Timedelta(days=int(period))
                        shifted_index = i - delta
                    else:
                        shifted_index = i - int(period)
                    if shifted_index in series.index:
                        shifted_series.loc[i] = series.loc[shifted_index]
                    else:
                        shifted_series.loc[i] = np.nan
                else:
                    shifted_series.loc[i] = np.nan
            return shifted_series
        else:
            return series.shift(int(periods))

    def calculate_n2(index, n1_series):
        n1_value = n1_series.iloc[index]
        if pd.isna(n1_value):
            return np.nan
        shift_period = int(n1_value) + 1
        if index - shift_period >= 0:
            return n1_series.iloc[index - shift_period]
        else:
            return np.nan

    df['N2'] = [calculate_n2(i, df['N1']) for i in range(len(df))]

    def calculate_n3(index, n1_series, n2_series):
        n1_value = n1_series.iloc[index]
        if pd.isna(n1_value):
            return np.nan

        shift_n1_plus_2 = int(n1_value) + 2
        n2_shifted_value = n2_series.shift(shift_n1_plus_2).iloc[index]
        if pd.isna(n2_shifted_value):
            return np.nan

        shift_period = int(n1_value) + int(n2_shifted_value) + 2
        if index - shift_period >= 0:
            return n1_series.iloc[index - shift_period]
        else:
            return np.nan

    df['N3'] = [calculate_n3(i, df['N1'], df['N2']) for i in range(len(df))]

    df['CL1'] = df['Close'].rolling(window=int(df['N1'].max()) + 1 if pd.notna(df['N1'].max()) else 1, min_periods=1).min()
    df['DIFL1'] = df['DIF'].rolling(window=int(df['N1'].max()) + 1 if pd.notna(df['N1'].max()) else 1, min_periods=1).min()
    df['CL2'] = ref_series(df['CL1'], df['N1'] + 1)
    df['DIFL2'] = ref_series(df['DIFL1'], df['N1'] + 1)
    df['CL3'] = ref_series(df['CL2'], df['N2'] + 1)
    df['DIFL3'] = ref_series(df['DIFL2'], df['N2'] + 1)

    def get_power_of_ten(x):
        if abs(x) < 1 and x != 0:
            return 0
        elif x > 0:
            return int(math.log10(x))
        elif x < 0:
            return int(math.log10(-x))
        else:
            return 0

    df['PDIFL2'] = df['DIFL2'].apply(get_power_of_ten)
    df['MDIFL2'] = np.where(
        df['PDIFL2'] != 0,
        (df['DIFL2'] / (10 ** df['PDIFL2'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIFL2'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['PDIFL3'] = df['DIFL3'].apply(get_power_of_ten)
    df['MDIFL3'] = np.where(
        df['PDIFL3'] != 0,
        (df['DIFL3'] / (10 ** df['PDIFL3'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIFL3'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['MDIFB2'] = np.where(
        df['PDIFL2'] != 0,
        (df['DIF'] / (10 ** df['PDIFL2'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIF'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )
    df['MDIFB3'] = np.where(
        df['PDIFL3'] != 0,
        (df['DIF'] / (10 ** df['PDIFL3'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIF'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['直接底背离'] = (df['CL1'] < df['CL2']) & (df['MDIFB2'] > df['MDIFL2']) & (df['MACD'] < 0) & (df['MACD'].shift(1) < 0) & (df['MDIFB2'] <= df['MDIFB2'].shift(1))
    df['隔峰底背离'] = (df['CL1'] < df['CL3']) & (df['CL3'] < df['CL2']) & (df['MDIFB3'] > df['MDIFL3']) & (df['MACD'] < 0) & (df['MACD'].shift(1) < 0) & (df['MDIFB3'] <= df['MDIFB3'].shift(1))
    df['B'] = df['直接底背离'] | df['隔峰底背离']
    df['BG'] = ((df['MDIFB2'] > df['MDIFB2'].shift(1)) & df['直接底背离'].shift(1)) | ((df['MDIFB3'] > df['MDIFB3'].shift(1)) & df['隔峰底背离'].shift(1))
    df['底背离消失'] = (df['直接底背离'].shift(1) & (df['DIFL1'] <= df['DIFL2'])) | (df['隔峰底背离'].shift(1) & (df['DIFL1'] <= df['DIFL3']))

    df['TFILTER_B_钝化'] = df['B'] & (df['B'].shift(1) == False) & (df['MACD'] <= 0)
    df['TFILTER_消失_底'] = df['底背离消失'] & (df['底背离消失'].shift(1) == False) & (df['B'] == False)
    df['TFILTER_BG_形成'] = df['BG'] & (df['BG'].shift(1) == False) & (df['MACD'] <= 0)

    df['底钝化'] = df['TFILTER_B_钝化'].astype(int)
    df['底钝化消失'] = df['TFILTER_消失_底'].astype(int)
    df['底钝化形成'] = df['TFILTER_BG_形成'].astype(int)

    # === 顶部结构预警 ===
    df['金叉'] = (df['DIF'] > df['DEA']) & (df['DIF'].shift(1) <= df['DEA'].shift(1))
    df['M1'] = df['金叉'].rolling(window=len(df), min_periods=1).apply(lambda x: np.where(x[::-1])[0][0] if np.any(x) else np.nan, raw=True)

    def calculate_m2(index, m1_series):
        m1_value = m1_series.iloc[index]
        if pd.isna(m1_value):
            return np.nan
        shift_period = int(m1_value) + 1
        if index - shift_period >= 0:
            return m1_series.iloc[index - shift_period]
        else:
            return np.nan

    df['M2'] = [calculate_m2(i, df['M1']) for i in range(len(df))]

    def calculate_m3(index, m1_series, m2_series):
        m1_value = m1_series.iloc[index]
        if pd.isna(m1_value):
            return np.nan

        shift_m1_plus_2 = int(m1_value) + 2
        m2_shifted_value = m2_series.shift(shift_m1_plus_2).iloc[index]
        if pd.isna(m2_shifted_value):
            return np.nan

        shift_period = int(m1_value) + int(m2_shifted_value) + 2
        if index - shift_period >= 0:
            return m1_series.iloc[index - shift_period]
        else:
            return np.nan

    df['M3'] = [calculate_m3(i, df['M1'], df['M2']) for i in range(len(df))]

    df['CH1'] = df['Close'].rolling(window=int(df['M1'].max()) + 1 if pd.notna(df['M1'].max()) else 1, min_periods=1).max()
    df['DIFH1'] = df['DIF'].rolling(window=int(df['M1'].max()) + 1 if pd.notna(df['M1'].max()) else 1, min_periods=1).max()
    df['CH2'] = ref_series(df['CH1'], df['M1'] + 1)
    df['DIFH2'] = ref_series(df['DIFH1'], df['M1'] + 1)
    df['CH3'] = ref_series(df['CH2'], df['M2'] + 1)
    df['DIFH3'] = ref_series(df['DIFH2'], df['M2'] + 1)

    df['PDIFH2'] = df['DIFH2'].apply(get_power_of_ten)
    df['MDIFH2'] = np.where(
        df['PDIFH2'] != 0,
        (df['DIFH2'] / (10 ** df['PDIFH2'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIFH2'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['PDIFH3'] = df['DIFH3'].apply(get_power_of_ten)
    df['MDIFH3'] = np.where(
        df['PDIFH3'] != 0,
        (df['DIFH3'] / (10 ** df['PDIFH3'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIFH3'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['MDIFT2'] = np.where(
        df['PDIFH2'] != 0,
        (df['DIF'] / (10 ** df['PDIFH2'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIF'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )
    df['MDIFT3'] = np.where(
        df['PDIFH3'] != 0,
        (df['DIF'] / (10 ** df['PDIFH3'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIF'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['直接顶背离'] = (df['CH1'] > df['CH2']) & (df['MDIFT2'] < df['MDIFH2']) & (df['MACD'] > 0) & (df['MACD'].shift(1) > 0) & (df['MDIFT2'] >= df['MDIFT2'].shift(1))
    df['隔峰顶背离'] = (df['CH1'] > df['CH3']) & (df['CH3'] > df['CH2']) & (df['MDIFT3'] < df['MDIFH3']) & (df['MACD'] > 0) & (df['MACD'].shift(1) > 0) & (df['MDIFT3'] >= df['MDIFT3'].shift(1))
    df['T'] = df['直接顶背离'] | df['隔峰顶背离']
    df['TG'] = ((df['MDIFT2'] < df['MDIFT2'].shift(1)) & df['直接顶背离'].shift(1)) | ((df['MDIFT3'] < df['MDIFT3'].shift(1)) & df['隔峰顶背离'].shift(1))
    df['顶背离消失'] = (df['直接顶背离'].shift(1) & (df['DIFH1'] >= df['DIFH2'])) | (df['隔峰顶背离'].shift(1) & (df['DIFH1'] >= df['DIFH3']))

    df['TFILTER_T_钝化'] = df['T'] & (df['T'].shift(1) == False) & (df['MACD'] >= 0)
    df['TFILTER_消失_顶'] = df['顶背离消失'] & (df['顶背离消失'].shift(1) == False) & (df['T'] == False)
    df['TFILTER_TG_形成'] = df['TG'] & (df['TG'].shift(1) == False) & (df['MACD'] >= 0)

    df['顶钝化'] = df['TFILTER_T_钝化'].astype(int)
    df['顶钝化消失'] = df['TFILTER_消失_顶'].astype(int)
    df['顶钝化形成'] = df['TFILTER_TG_形成'].astype(int)

    return df

def translate_mylanguage_macd_divergence_with_triggers(df):
    """
    将给定的包含 'Close' 列的 Pandas DataFrame 转换为包含 MACD 相关指标和背离信号的 DataFrame，
    并返回包含钝化和消失信号的列。
    """

    # === MACD 指标计算 ===
    ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = 100 * (ema_12 - ema_26)
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD'] = (df['DIF'] - df['DEA']) * 2

    # === 底部结构预警 ===
    df['死叉'] = (df['DEA'] > df['DIF']) & (df['DEA'].shift(1) <= df['DIF'].shift(1))
    df['N1'] = df['死叉'].rolling(window=len(df), min_periods=1).apply(lambda x: np.where(x[::-1])[0][0] if np.any(x) else np.nan, raw=True)

    def ref_series(series, periods):
        if isinstance(periods, pd.Series):
            shifted_series = pd.Series(index=series.index, dtype=series.dtype)
            for i, period in periods.items():
                if pd.notna(period):
                    if isinstance(i, pd.Timestamp):
                        delta = pd.Timedelta(days=int(period))
                        shifted_index = i - delta
                    else:
                        shifted_index = i - int(period)
                    if shifted_index in series.index:
                        shifted_series.loc[i] = series.loc[shifted_index]
                    else:
                        shifted_series.loc[i] = np.nan
                else:
                    shifted_series.loc[i] = np.nan
            return shifted_series
        else:
            return series.shift(int(periods))

    def calculate_n2(index, n1_series):
        n1_value = n1_series.iloc[index]
        if pd.isna(n1_value):
            return np.nan
        shift_period = int(n1_value) + 1
        if index - shift_period >= 0:
            return n1_series.iloc[index - shift_period]
        else:
            return np.nan

    df['N2'] = [calculate_n2(i, df['N1']) for i in range(len(df))]

    def calculate_n3(index, n1_series, n2_series):
        n1_value = n1_series.iloc[index]
        if pd.isna(n1_value):
            return np.nan

        shift_n1_plus_2 = int(n1_value) + 2
        n2_shifted_value = n2_series.shift(shift_n1_plus_2).iloc[index]
        if pd.isna(n2_shifted_value):
            return np.nan

        shift_period = int(n1_value) + int(n2_shifted_value) + 2
        if index - shift_period >= 0:
            return n1_series.iloc[index - shift_period]
        else:
            return np.nan

    df['N3'] = [calculate_n3(i, df['N1'], df['N2']) for i in range(len(df))]

    df['CL1'] = df['Close'].rolling(window=int(df['N1'].max()) + 1 if pd.notna(df['N1'].max()) else 1, min_periods=1).min()
    df['DIFL1'] = df['DIF'].rolling(window=int(df['N1'].max()) + 1 if pd.notna(df['N1'].max()) else 1, min_periods=1).min()
    df['CL2'] = ref_series(df['CL1'], df['N1'] + 1)
    df['DIFL2'] = ref_series(df['DIFL1'], df['N1'] + 1)
    df['CL3'] = ref_series(df['CL2'], df['N2'] + 1)
    df['DIFL3'] = ref_series(df['DIFL2'], df['N2'] + 1)

    def get_power_of_ten(x):
        if abs(x) < 1 and x != 0:
            return 0
        elif x > 0:
            return int(math.log10(x))
        elif x < 0:
            return int(math.log10(-x))
        else:
            return 0

    df['PDIFL2'] = df['DIFL2'].apply(get_power_of_ten)
    df['MDIFL2'] = np.where(
        df['PDIFL2'] != 0,
        (df['DIFL2'] / (10 ** df['PDIFL2'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIFL2'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['PDIFL3'] = df['DIFL3'].apply(get_power_of_ten)
    df['MDIFL3'] = np.where(
        df['PDIFL3'] != 0,
        (df['DIFL3'] / (10 ** df['PDIFL3'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIFL3'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['MDIFB2'] = np.where(
        df['PDIFL2'] != 0,
        (df['DIF'] / (10 ** df['PDIFL2'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIF'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )
    df['MDIFB3'] = np.where(
        df['PDIFL3'] != 0,
        (df['DIF'] / (10 ** df['PDIFL3'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIF'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['直接底背离'] = (df['CL1'] < df['CL2']) & (df['MDIFB2'] > df['MDIFL2']) & (df['MACD'] < 0) & (df['MACD'].shift(1) < 0) & (df['MDIFB2'] <= df['MDIFB2'].shift(1))
    df['隔峰底背离'] = (df['CL1'] < df['CL3']) & (df['CL3'] < df['CL2']) & (df['MDIFB3'] > df['MDIFL3']) & (df['MACD'] < 0) & (df['MACD'].shift(1) < 0) & (df['MDIFB3'] <= df['MDIFB3'].shift(1))
    df['B'] = df['直接底背离'] | df['隔峰底背离']
    df['BG'] = ((df['MDIFB2'] > df['MDIFB2'].shift(1)) & df['直接底背离'].shift(1)) | ((df['MDIFB3'] > df['MDIFB3'].shift(1)) & df['隔峰底背离'].shift(1))
    df['底背离消失'] = (df['直接底背离'].shift(1) & (df['DIFL1'] <= df['DIFL2'])) | (df['隔峰底背离'].shift(1) & (df['DIFL1'] <= df['DIFL3']))

    df['TFILTER_B_钝化'] = df['B'] & (df['B'].shift(1) == False) & (df['MACD'] <= 0)
    df['TFILTER_消失_底'] = df['底背离消失'] & (df['底背离消失'].shift(1) == False) & (df['B'] == False)
    df['TFILTER_BG_形成'] = df['BG'] & (df['BG'].shift(1) == False) & (df['MACD'] <= 0)

    df['底钝化'] = df['TFILTER_B_钝化'].astype(int)
    df['底钝化消失'] = df['TFILTER_消失_底'].astype(int)
    df['底钝化形成'] = df['TFILTER_BG_形成'].astype(int)

    # === 顶部结构预警 ===
    df['金叉'] = (df['DIF'] > df['DEA']) & (df['DIF'].shift(1) <= df['DEA'].shift(1))
    df['M1'] = df['金叉'].rolling(window=len(df), min_periods=1).apply(lambda x: np.where(x[::-1])[0][0] if np.any(x) else np.nan, raw=True)

    def calculate_m2(index, m1_series):
        m1_value = m1_series.iloc[index]
        if pd.isna(m1_value):
            return np.nan
        shift_period = int(m1_value) + 1
        if index - shift_period >= 0:
            return m1_series.iloc[index - shift_period]
        else:
            return np.nan

    df['M2'] = [calculate_m2(i, df['M1']) for i in range(len(df))]

    def calculate_m3(index, m1_series, m2_series):
        m1_value = m1_series.iloc[index]
        if pd.isna(m1_value):
            return np.nan

        shift_m1_plus_2 = int(m1_value) + 2
        m2_shifted_value = m2_series.shift(shift_m1_plus_2).iloc[index]
        if pd.isna(m2_shifted_value):
            return np.nan

        shift_period = int(m1_value) + int(m2_shifted_value) + 2
        if index - shift_period >= 0:
            return m1_series.iloc[index - shift_period]
        else:
            return np.nan

    df['M3'] = [calculate_m3(i, df['M1'], df['M2']) for i in range(len(df))]

    df['CH1'] = df['Close'].rolling(window=int(df['M1'].max()) + 1 if pd.notna(df['M1'].max()) else 1, min_periods=1).max()
    df['DIFH1'] = df['DIF'].rolling(window=int(df['M1'].max()) + 1 if pd.notna(df['M1'].max()) else 1, min_periods=1).max()
    df['CH2'] = ref_series(df['CH1'], df['M1'] + 1)
    df['DIFH2'] = ref_series(df['DIFH1'], df['M1'] + 1)
    df['CH3'] = ref_series(df['CH2'], df['M2'] + 1)
    df['DIFH3'] = ref_series(df['DIFH2'], df['M2'] + 1)

    df['PDIFH2'] = df['DIFH2'].apply(get_power_of_ten)
    df['MDIFH2'] = np.where(
        df['PDIFH2'] != 0,
        (df['DIFH2'] / (10 ** df['PDIFH2'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIFH2'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['PDIFH3'] = df['DIFH3'].apply(get_power_of_ten)
    df['MDIFH3'] = np.where(
        df['PDIFH3'] != 0,
        (df['DIFH3'] / (10 ** df['PDIFH3'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIFH3'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['MDIFT2'] = np.where(
        df['PDIFH2'] != 0,
        (df['DIF'] / (10 ** df['PDIFH2'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIF'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )
    df['MDIFT3'] = np.where(
        df['PDIFH3'] != 0,
        (df['DIF'] / (10 ** df['PDIFH3'])).replace([np.inf, -np.inf], np.nan).fillna(0).astype(int),
        df['DIF'].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
    )

    df['直接顶背离'] = (df['CH1'] > df['CH2']) & (df['MDIFT2'] < df['MDIFH2']) & (df['MACD'] > 0) & (df['MACD'].shift(1) > 0) & (df['MDIFT2'] >= df['MDIFT2'].shift(1))
    df['隔峰顶背离'] = (df['CH1'] > df['CH3']) & (df['CH3'] > df['CH2']) & (df['MDIFT3'] < df['MDIFH3']) & (df['MACD'] > 0) & (df['MACD'].shift(1) > 0) & (df['MDIFT3'] >= df['MDIFT3'].shift(1))
    df['T'] = df['直接顶背离'] | df['隔峰顶背离']
    df['TG'] = ((df['MDIFT2'] < df['MDIFT2'].shift(1)) & df['直接顶背离'].shift(1)) | ((df['MDIFT3'] < df['MDIFT3'].shift(1)) & df['隔峰顶背离'].shift(1))
    df['顶背离消失'] = (df['直接顶背离'].shift(1) & (df['DIFH1'] >= df['DIFH2'])) | (df['隔峰顶背离'].shift(1) & (df['DIFH1'] >= df['DIFH3']))

    df['TFILTER_T_钝化'] = df['T'] & (df['T'].shift(1) == False) & (df['MACD'] >= 0)
    df['TFILTER_消失_顶'] = df['顶背离消失'] & (df['顶背离消失'].shift(1) == False) & (df['T'] == False)
    df['TFILTER_TG_形成'] = df['TG'] & (df['TG'].shift(1) == False) & (df['MACD'] >= 0)

    df['顶钝化'] = df['TFILTER_T_钝化'].astype(int)
    df['顶钝化消失'] = df['TFILTER_消失_顶'].astype(int)
    df['顶钝化形成'] = df['TFILTER_TG_形成'].astype(int)

    columns_to_output = ['底钝化', '底钝化消失', '底钝化形成', '顶钝化', '顶钝化消失', '顶钝化形成']
    return df[columns_to_output]