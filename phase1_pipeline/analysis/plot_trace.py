"""
Ray Tracing Trace Analysis and Visualization
Reads ns3_trace.csv and generates comprehensive plots
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import seaborn as sns

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 6)

def load_trace(csv_path):
    """Load CSV trace file"""
    df = pd.read_csv(csv_path)
    df['timestamp_s'] = df['timestamp_ns'] / 1e9
    df['amplitude_magnitude'] = np.sqrt(df['amplitude_real']**2 + df['amplitude_imag']**2)
    df['amplitude_db'] = 20 * np.log10(df['amplitude_magnitude'] + 1e-12)
    return df

def plot_amplitude_timeline(df, output_dir):
    """Plot amplitude over time"""
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))
    
    # Amplitude magnitude vs time
    for los_flag in [0, 1]:
        label = "LOS" if los_flag == 1 else "NLOS"
        data = df[df['los_flag'] == los_flag]
        axes[0].scatter(data['timestamp_s']*1000, data['amplitude_magnitude'], 
                       label=label, alpha=0.5, s=20)
    
    axes[0].set_xlabel('Time (ms)')
    axes[0].set_ylabel('Amplitude (linear)')
    axes[0].set_title('Path Amplitude vs Time')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    
    # Amplitude in dB vs time
    for los_flag in [0, 1]:
        label = "LOS" if los_flag == 1 else "NLOS"
        data = df[df['los_flag'] == los_flag]
        axes[1].scatter(data['timestamp_s']*1000, data['amplitude_db'], 
                       label=label, alpha=0.5, s=20)
    
    axes[1].set_xlabel('Time (ms)')
    axes[1].set_ylabel('Amplitude (dB)')
    axes[1].set_title('Path Amplitude (dB) vs Time')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'amplitude_vs_time.png', dpi=150)
    plt.close()
    print("✓ Saved: amplitude_vs_time.png")

def plot_delay_timeline(df, output_dir):
    """Plot propagation delay over time"""
    fig, ax = plt.subplots(figsize=(14, 6))
    
    for los_flag in [0, 1]:
        label = "LOS" if los_flag == 1 else "NLOS"
        data = df[df['los_flag'] == los_flag]
        ax.scatter(data['timestamp_s']*1000, data['delay_s']*1e6, 
                  label=label, alpha=0.5, s=20)
    
    ax.set_xlabel('Time (ms)')
    ax.set_ylabel('Propagation Delay (μs)')
    ax.set_title('Path Delay vs Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'delay_vs_time.png', dpi=150)
    plt.close()
    print("✓ Saved: delay_vs_time.png")

def plot_doppler_timeline(df, output_dir):
    """Plot Doppler shift over time"""
    fig, ax = plt.subplots(figsize=(14, 6))
    
    for los_flag in [0, 1]:
        label = "LOS" if los_flag == 1 else "NLOS"
        data = df[df['los_flag'] == los_flag]
        ax.scatter(data['timestamp_s']*1000, data['doppler_hz'], 
                  label=label, alpha=0.5, s=20)
    
    ax.set_xlabel('Time (ms)')
    ax.set_ylabel('Doppler Shift (Hz)')
    ax.set_title('Doppler Shift vs Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color='k', linestyle='--', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'doppler_vs_time.png', dpi=150)
    plt.close()
    print("✓ Saved: doppler_vs_time.png")

def plot_aoa_aod_distribution(df, output_dir):
    """Plot Angle of Arrival and Angle of Departure distributions"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # AoA theta
    axes[0, 0].hist(df['aoa_theta_rad'] * 180/np.pi, bins=30, alpha=0.7, edgecolor='black')
    axes[0, 0].set_xlabel('AoA Theta (degrees)')
    axes[0, 0].set_ylabel('Count')
    axes[0, 0].set_title('Angle of Arrival - Theta Distribution')
    axes[0, 0].grid(True, alpha=0.3)
    
    # AoA phi
    axes[0, 1].hist(df['aoa_phi_rad'] * 180/np.pi, bins=30, alpha=0.7, edgecolor='black', color='orange')
    axes[0, 1].set_xlabel('AoA Phi (degrees)')
    axes[0, 1].set_ylabel('Count')
    axes[0, 1].set_title('Angle of Arrival - Phi Distribution')
    axes[0, 1].grid(True, alpha=0.3)
    
    # AoD theta
    axes[1, 0].hist(df['aod_theta_rad'] * 180/np.pi, bins=30, alpha=0.7, edgecolor='black', color='green')
    axes[1, 0].set_xlabel('AoD Theta (degrees)')
    axes[1, 0].set_ylabel('Count')
    axes[1, 0].set_title('Angle of Departure - Theta Distribution')
    axes[1, 0].grid(True, alpha=0.3)
    
    # AoD phi
    axes[1, 1].hist(df['aod_phi_rad'] * 180/np.pi, bins=30, alpha=0.7, edgecolor='black', color='red')
    axes[1, 1].set_xlabel('AoD Phi (degrees)')
    axes[1, 1].set_ylabel('Count')
    axes[1, 1].set_title('Angle of Departure - Phi Distribution')
    axes[1, 1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'aoa_aod_distribution.png', dpi=150)
    plt.close()
    print("✓ Saved: aoa_aod_distribution.png")

def plot_phase_timeline(df, output_dir):
    """Plot phase over time"""
    fig, ax = plt.subplots(figsize=(14, 6))
    
    for los_flag in [0, 1]:
        label = "LOS" if los_flag == 1 else "NLOS"
        data = df[df['los_flag'] == los_flag]
        ax.scatter(data['timestamp_s']*1000, data['phase_rad'] * 180/np.pi, 
                  label=label, alpha=0.5, s=20)
    
    ax.set_xlabel('Time (ms)')
    ax.set_ylabel('Phase (degrees)')
    ax.set_title('Phase vs Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'phase_vs_time.png', dpi=150)
    plt.close()
    print("✓ Saved: phase_vs_time.png")

def plot_los_vs_nlos_statistics(df, output_dir):
    """Plot LOS vs NLOS statistics"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    los_data = df[df['los_flag'] == 1]
    nlos_data = df[df['los_flag'] == 0]
    
    # Amplitude comparison
    axes[0, 0].boxplot([los_data['amplitude_db'], nlos_data['amplitude_db']], 
                        tick_labels=['LOS', 'NLOS'])
    axes[0, 0].set_ylabel('Amplitude (dB)')
    axes[0, 0].set_title('Amplitude Distribution: LOS vs NLOS')
    axes[0, 0].grid(True, alpha=0.3)
    
    # Delay comparison
    axes[0, 1].boxplot([los_data['delay_s']*1e6, nlos_data['delay_s']*1e6], 
                        tick_labels=['LOS', 'NLOS'])
    axes[0, 1].set_ylabel('Delay (μs)')
    axes[0, 1].set_title('Delay Distribution: LOS vs NLOS')
    axes[0, 1].grid(True, alpha=0.3)
    
    # Doppler comparison
    axes[1, 0].boxplot([los_data['doppler_hz'], nlos_data['doppler_hz']], 
                        tick_labels=['LOS', 'NLOS'])
    axes[1, 0].set_ylabel('Doppler (Hz)')
    axes[1, 0].set_title('Doppler Distribution: LOS vs NLOS')
    axes[1, 0].grid(True, alpha=0.3)
    
    # Path count over time
    path_count = df.groupby('timestamp_s').size()
    los_count = df[df['los_flag'] == 1].groupby('timestamp_s').size()
    nlos_count = df[df['los_flag'] == 0].groupby('timestamp_s').size()
    
    # Reindex to fill missing timestamps with 0
    los_count = los_count.reindex(path_count.index, fill_value=0)
    nlos_count = nlos_count.reindex(path_count.index, fill_value=0)
    
    axes[1, 1].plot(path_count.index*1000, los_count.values, label='LOS', marker='o', markersize=3)
    axes[1, 1].plot(path_count.index*1000, nlos_count.values, label='NLOS', marker='s', markersize=3)
    axes[1, 1].set_xlabel('Time (ms)')
    axes[1, 1].set_ylabel('Path Count')
    axes[1, 1].set_title('Path Count vs Time')
    axes[1, 1].legend()
    axes[1, 1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'los_vs_nlos_statistics.png', dpi=150)
    plt.close()
    print("✓ Saved: los_vs_nlos_statistics.png")

def plot_path_id_evolution(df, output_dir):
    """Plot how individual paths evolve over time"""
    fig, ax = plt.subplots(figsize=(14, 8))
    
    unique_paths = df['path_id'].unique()
    colors = plt.cm.tab20(np.linspace(0, 1, len(unique_paths)))
    
    for idx, path_id in enumerate(sorted(unique_paths)[:10]):  # Top 10 paths
        data = df[df['path_id'] == path_id]
        ax.plot(data['timestamp_s']*1000, data['amplitude_db'], 
               label=f'Path {path_id}', marker='o', markersize=2, color=colors[idx])
    
    ax.set_xlabel('Time (ms)')
    ax.set_ylabel('Amplitude (dB)')
    ax.set_title('Individual Path Evolution (Top 10 Paths)')
    ax.legend(loc='best', fontsize=9)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'path_evolution.png', dpi=150)
    plt.close()
    print("✓ Saved: path_evolution.png")

def plot_power_delay_profile(df, output_dir):
    """Plot Power Delay Profile (PDP)"""
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Group by delay and sum power
    power_vs_delay = df.groupby('delay_s')['amplitude_magnitude'].sum()
    
    ax.stem(power_vs_delay.index*1e6, 10*np.log10(power_vs_delay.values), basefmt=' ')
    ax.set_xlabel('Delay (μs)')
    ax.set_ylabel('Power (dB)')
    ax.set_title('Power Delay Profile (PDP)')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'power_delay_profile.png', dpi=150)
    plt.close()
    print("✓ Saved: power_delay_profile.png")

def plot_rms_delay_spread(df, output_dir):
    """Calculate and plot RMS delay spread over time"""
    fig, ax = plt.subplots(figsize=(14, 6))
    
    rms_delays = []
    timestamps = []
    
    for ts in df['timestamp_s'].unique():
        ts_data = df[df['timestamp_s'] == ts]
        delays = ts_data['delay_s'].values
        powers = ts_data['amplitude_magnitude'].values**2
        
        # Mean delay
        mean_delay = np.sum(delays * powers) / np.sum(powers)
        
        # RMS delay spread
        rms_delay = np.sqrt(np.sum((delays - mean_delay)**2 * powers) / np.sum(powers))
        
        timestamps.append(ts)
        rms_delays.append(rms_delay)
    
    ax.plot(np.array(timestamps)*1000, np.array(rms_delays)*1e9, marker='o', markersize=3)
    ax.set_xlabel('Time (ms)')
    ax.set_ylabel('RMS Delay Spread (ns)')
    ax.set_title('RMS Delay Spread vs Time')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'rms_delay_spread.png', dpi=150)
    plt.close()
    print("✓ Saved: rms_delay_spread.png")

def plot_2d_angle_distribution(df, output_dir):
    """Plot 2D angle distribution (AoA/AoD scatter)"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), subplot_kw=dict(projection='polar'))
    
    # AoA distribution
    theta = df['aoa_theta_rad']
    phi = df['aoa_phi_rad']
    axes[0].scatter(phi, theta * 180/np.pi, c=df['amplitude_db'], s=20, cmap='viridis', alpha=0.6)
    axes[0].set_title('Angle of Arrival (AoA)\n(Phi vs Theta)')
    axes[0].set_ylim([0, 180])
    
    # AoD distribution
    theta = df['aod_theta_rad']
    phi = df['aod_phi_rad']
    axes[1].scatter(phi, theta * 180/np.pi, c=df['amplitude_db'], s=20, cmap='plasma', alpha=0.6)
    axes[1].set_title('Angle of Departure (AoD)\n(Phi vs Theta)')
    axes[1].set_ylim([0, 180])
    
    plt.tight_layout()
    plt.savefig(output_dir / '2d_angle_distribution.png', dpi=150)
    plt.close()
    print("✓ Saved: 2d_angle_distribution.png")

def plot_summary_statistics(df, output_dir):
    """Plot summary statistics"""
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
    
    # Summary text
    ax_text = fig.add_subplot(gs[0, :])
    ax_text.axis('off')
    
    total_paths = len(df)
    los_paths = len(df[df['los_flag'] == 1])
    nlos_paths = len(df[df['los_flag'] == 0])
    num_timestamps = df['timestamp_s'].nunique()
    
    summary_text = f"""
    TRACE ANALYSIS SUMMARY
    ═══════════════════════════════════════════════════════════
    
    Total Paths:           {total_paths:,}
    LOS Paths:             {los_paths:,} ({100*los_paths/total_paths:.1f}%)
    NLOS Paths:            {nlos_paths:,} ({100*nlos_paths/total_paths:.1f}%)
    
    Time Duration:         {df['timestamp_s'].max():.3f} s ({df['timestamp_s'].max()*1000:.1f} ms)
    Number of Snapshots:   {num_timestamps}
    Avg Paths/Snapshot:    {total_paths/num_timestamps:.1f}
    
    Amplitude Statistics:
      Min: {df['amplitude_db'].min():.1f} dB
      Max: {df['amplitude_db'].max():.1f} dB
      Mean: {df['amplitude_db'].mean():.1f} dB
    
    Delay Statistics:
      Min: {df['delay_s'].min()*1e6:.3f} μs
      Max: {df['delay_s'].max()*1e6:.3f} μs
      Mean: {df['delay_s'].mean()*1e6:.3f} μs
    
    Doppler Statistics:
      Min: {df['doppler_hz'].min():.1f} Hz
      Max: {df['doppler_hz'].max():.1f} Hz
      Mean: {df['doppler_hz'].mean():.1f} Hz
    """
    
    ax_text.text(0.05, 0.95, summary_text, transform=ax_text.transAxes,
                fontfamily='monospace', fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Histograms
    ax1 = fig.add_subplot(gs[1, 0])
    ax1.hist(df['amplitude_db'], bins=50, edgecolor='black', alpha=0.7)
    ax1.set_xlabel('Amplitude (dB)')
    ax1.set_ylabel('Frequency')
    ax1.set_title('Amplitude Distribution')
    ax1.grid(True, alpha=0.3)
    
    ax2 = fig.add_subplot(gs[1, 1])
    ax2.hist(df['delay_s']*1e6, bins=50, edgecolor='black', alpha=0.7, color='orange')
    ax2.set_xlabel('Delay (μs)')
    ax2.set_ylabel('Frequency')
    ax2.set_title('Delay Distribution')
    ax2.grid(True, alpha=0.3)
    
    ax3 = fig.add_subplot(gs[1, 2])
    ax3.hist(df['doppler_hz'], bins=50, edgecolor='black', alpha=0.7, color='green')
    ax3.set_xlabel('Doppler (Hz)')
    ax3.set_ylabel('Frequency')
    ax3.set_title('Doppler Distribution')
    ax3.grid(True, alpha=0.3)
    
    # Pie chart
    ax4 = fig.add_subplot(gs[2, 0])
    ax4.pie([los_paths, nlos_paths], labels=['LOS', 'NLOS'], autopct='%1.1f%%',
           colors=['#2ecc71', '#e74c3c'], startangle=90)
    ax4.set_title('LOS vs NLOS Distribution')
    
    # Path count per snapshot
    ax5 = fig.add_subplot(gs[2, 1:])
    path_counts = df.groupby('timestamp_s').size()
    ax5.plot(path_counts.index*1000, path_counts.values, marker='o', markersize=3)
    ax5.set_xlabel('Time (ms)')
    ax5.set_ylabel('Paths per Snapshot')
    ax5.set_title('Paths per Snapshot vs Time')
    ax5.grid(True, alpha=0.3)
    
    plt.savefig(output_dir / 'summary_statistics.png', dpi=150)
    plt.close()
    print("✓ Saved: summary_statistics.png")

def main():
    """Main function"""
    # File paths
    output_dir = Path(__file__).parent.parent / 'output'
    csv_file = output_dir / 'ns3_trace.csv'
    plots_dir = output_dir / 'plots'
    plots_dir.mkdir(exist_ok=True)
    
    # Check if CSV exists
    if not csv_file.exists():
        print(f"❌ Error: {csv_file} not found!")
        return
    
    print(f"📂 Loading trace file: {csv_file}")
    df = load_trace(csv_file)
    print(f"📊 Loaded {len(df)} records from {df['timestamp_s'].nunique()} timestamps\n")
    
    # Generate plots
    print("📈 Generating plots...")
    plot_amplitude_timeline(df, plots_dir)
    plot_delay_timeline(df, plots_dir)
    plot_doppler_timeline(df, plots_dir)
    plot_aoa_aod_distribution(df, plots_dir)
    plot_phase_timeline(df, plots_dir)
    plot_los_vs_nlos_statistics(df, plots_dir)
    plot_path_id_evolution(df, plots_dir)
    plot_power_delay_profile(df, plots_dir)
    plot_rms_delay_spread(df, plots_dir)
    plot_2d_angle_distribution(df, plots_dir)
    plot_summary_statistics(df, plots_dir)
    
    print(f"\n✅ All plots saved to: {plots_dir}")
    print(f"Total plots generated: 11")

if __name__ == "__main__":
    main()
