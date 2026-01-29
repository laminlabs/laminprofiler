# laminprofiler: Analyze GitHub contributions

A simple Python API to fetch and plot GitHub contributions across repositories.

Install:

```bash
pip install laminprofiler
```

Fetch data:

```python
import laminprofiler
fetcher = laminprofiler.Fetcher("laminlabs")  # pass the organization
df = fetcher.fetch_contribs("lamindb")  # pass one or multiple repositories
df.head()
#>	date		author		repo	type	title											...
#>	2025-10-11	falexwolf	lamindb	commit	🚸 Better UX for `lamin annotate` CLI command	...
#>	2025-10-10	Koncopd		lamindb	commit	🐛 Various fixes for filtering (#3147)			...
#>	2025-10-10	falexwolf	lamindb	commit	🐛 Do not retrieve records from trash based on	...
```

Plot data:

```python
plotter = laminprofiler.Plotter(df)
plotter.plot_total_number_by_author_by_type()
```

<img width="500" height="624" alt="image" src="https://github.com/user-attachments/assets/29a872ac-e244-4ac8-a24f-a66706a20761" />

```python
plotter.plot_number_by_month_by_author()
```

<img width="500" height="624" alt="image" src="https://github.com/user-attachments/assets/cfa31614-352b-469f-bf48-eeaca29cd5dd" />

If you want to make such analyses reproducible: [here](https://lamin.ai/laminlabs/lamindata/transform/X1ZxsmZxISxW) is how to track the notebooks, environments, and input & ouput data for these plots.

PS: You can also fetch all repos with activity in a year.

```python
fetcher.fetch_repos()
```
