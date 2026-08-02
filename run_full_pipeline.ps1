Write-Host "Running Sports Projection Bot Pipeline..." -ForegroundColor Cyan

python run_pipeline.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Pipeline completed with failures. Review the summary above before launching the dashboard." -ForegroundColor Yellow
    exit $LASTEXITCODE
}

Write-Host "Pipeline complete. Launching dashboard..." -ForegroundColor Green
streamlit run master_dashboard.py
